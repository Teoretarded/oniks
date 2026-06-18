"""Doctrinally varied enemy ship classes for COMBAT mode (M5).

The Phase-2 fleet was homogeneous: every escort was a ``Destroyer`` with one
fixed loadout.  M5 turns the task group into a varied formation — a ground-
attack TLAM bank, a dedicated air-defense escort, a general-purpose destroyer
(numerically identical to today's Destroyer), and a CEC datalink-hub Flagship.

Design
------
Each class is a ``Destroyer`` subclass whose ONLY difference is the magazine /
HP / dimension loadout it consumes in ``__init__`` and a frozen ``ShipClassDef``
describing it.  This mirrors how ``Carrier`` (sim/enemy_air.py) overrides the
Destroyer params from a SHIP_TYPES entry — the racetrack station-keeping loop,
the damage ladder, the SPY-1 radar sync and the OBB are all reused unchanged.

Two new per-unit knobs the integration layer reads through ``getattr`` with a
fallback (so the LOCKED enemy_defense tests stay green for a plain Destroyer):

  * ``sm2_max_inflight`` — the simultaneous-SM-2 cap (sim/enemy_defense.py
    reads ``getattr(ship, 'sm2_max_inflight', SM2_MAX_INFLIGHT)``).  An
    AirDefenseShip sustains MORE concurrent rounds than a general destroyer.
  * ``_track_form_s`` — the per-unit continuous-visibility delay before a
    fire-control track forms (default = TRACK_FORM_S).  The world RAISES this
    on the surviving escorts when the flagship CEC hub dies (cohesion loss),
    so the fleet reacts slower with the datalink down — a SENSOR-honest nerf.

  * ``is_datalink_hub`` — True only for the Flagship; DESCRIPTIVE/test-only.
    The world identifies the hub structurally via ``isinstance(s, Flagship)``
    (world/combat.py: self.flagship, _check_flagship_cec, _enemy_cue_radars) —
    that isinstance check is the SINGLE SOURCE OF TRUTH for "is this the hub",
    and the world drops the dead hub's live radar from the escorts' remote-cue
    set when it sinks.  The flag documents intent and lets a hull assert its
    own role without an import; it deliberately does NOT drive any world logic.

BYTE-IDENTICAL GATE: the default fleet builds GeneralDestroyer hulls whose
ship_type is still "destroyer" and whose every magazine/dim/HP matches today's
Destroyer exactly, so sample_fleet / the duel / the smoke determinism check /
the default battle stay bit-identical (all new fleet-mixer counts default 0).

DEFERRED: new MESHES are a later model pass — every class reuses the existing
"destroyer" mesh (ship_type "flagship"/"aaw_destroyer"/"ground_attack_destroyer"
register their dims/HP in SHIP_TYPES, but the renderer falls back to the
destroyer mesh until a dedicated hull lands).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sim.enemy_defense import SM2_MAX_INFLIGHT, TRACK_FORM_S
from sim.enemy_ships import (Destroyer, _CIWS_AMMO_DEFAULT, _SM2_AMMO_DEFAULT,
                             _SM6_AMMO_DEFAULT, _TOMAHAWK_AMMO_DEFAULT)
from sim.ships import HULL_DRAFT, SHIP_TYPES


@dataclass(frozen=True)
class ShipClassDef:
    """Immutable per-class loadout / hull description.

    ``ship_type`` is the SHIP_TYPES key (and the dims/HP source).  ``role`` is
    a short doctrinal label for tooling / debugging (never leaked to the player
    contact board — see the module docstring's fog note).  The magazine fields
    feed the Destroyer ctor; ``sm2_max_inflight`` and ``track_form_s`` are the
    per-unit fire-control knobs the controller reads via getattr.
    """

    role: str
    ship_type: str
    sm2_ammo: int
    sm6_ammo: int
    ciws_ammo: int
    tomahawk_ammo: int
    sm2_max_inflight: int
    is_datalink_hub: bool = False
    track_form_s: float = TRACK_FORM_S


# --- SHIP_TYPES registration (dims/HP) ---------------------------------------
# The general destroyer reuses the existing "destroyer" entry verbatim (byte-
# identical default fleet).  The new hulls register their own dims/HP; the
# renderer falls back to the destroyer mesh until a dedicated model ships.

# Air-defense escort: a Burke-flight-III-class AAW hull — same dimensions as
# the general destroyer (it IS a Burke), HP 3.  Its difference is loadout +
# fire-control channels, not size.
SHIP_TYPES["aaw_destroyer"] = dict(
    length=155.0, beam=20.0, height=30.0, speed=15.0, hp=3)

# Ground-attack escort: same Burke hull, HP 3; the TLAM-heavy loadout is the
# difference.
SHIP_TYPES["ground_attack_destroyer"] = dict(
    length=155.0, beam=20.0, height=30.0, speed=15.0, hp=3)

# Flagship: a larger Ticonderoga/command-cruiser-class hull — HP 4 (the CEC
# hub is a high-value, harder-to-sink unit), slightly longer.
SHIP_TYPES["flagship"] = dict(
    length=173.0, beam=17.0, height=33.0, speed=15.0, hp=4)


# --- Class defs --------------------------------------------------------------

# General destroyer: NUMERICALLY today's Destroyer (byte-identical default).
GENERAL_DESTROYER_DEF = ShipClassDef(
    role="general",
    ship_type="destroyer",
    sm2_ammo=_SM2_AMMO_DEFAULT,          # 24
    sm6_ammo=_SM6_AMMO_DEFAULT,          # 6
    ciws_ammo=_CIWS_AMMO_DEFAULT,        # 1500
    tomahawk_ammo=_TOMAHAWK_AMMO_DEFAULT,  # 8
    sm2_max_inflight=SM2_MAX_INFLIGHT,   # 4 (the LOCKED const)
    is_datalink_hub=False,
)

# Air-defense escort: a deep SM-2 magazine and a HIGHER simultaneous cap (it
# is built to soak a saturation raid), plus extra SM-6 area rounds.  No TLAM —
# this hull is pure shield, not spear.
AIR_DEFENSE_DEF = ShipClassDef(
    role="air_defense",
    ship_type="aaw_destroyer",
    sm2_ammo=40,                # deeper magazine than the general's 24
    sm6_ammo=12,                # extra area-air rounds
    ciws_ammo=_CIWS_AMMO_DEFAULT,
    tomahawk_ammo=0,            # no land-attack: a dedicated shield
    sm2_max_inflight=8,         # twice the general's 4 — more concurrent shots
    is_datalink_hub=False,
)

# Ground-attack escort: a heavy TLAM bank (the spear), a thin self-defense SM-2
# load.  Its TLAM cells DRAIN FIRST in a salvo (world/combat.py salvo ordering).
GROUND_ATTACK_DEF = ShipClassDef(
    role="ground_attack",
    ship_type="ground_attack_destroyer",
    sm2_ammo=8,                 # token self-defense
    sm6_ammo=0,
    ciws_ammo=_CIWS_AMMO_DEFAULT,
    tomahawk_ammo=40,           # the deep land-attack bank
    sm2_max_inflight=SM2_MAX_INFLIGHT,
    is_datalink_hub=False,
)

# Flagship: the CEC datalink hub.  A capable shield in its own right (large
# SM-2/SM-6 load, high cap) but its real value is the remote cue it provides
# the escorts; when it sinks the fleet falls back to own-SPY-1 + slower
# cohesion (world wiring).
FLAGSHIP_DEF = ShipClassDef(
    role="flagship",
    ship_type="flagship",
    sm2_ammo=48,
    sm6_ammo=12,
    ciws_ammo=_CIWS_AMMO_DEFAULT,
    tomahawk_ammo=0,
    sm2_max_inflight=8,
    is_datalink_hub=True,
)


# --- Subclasses --------------------------------------------------------------

class _ClassedDestroyer(Destroyer):
    """Common ctor: build a Destroyer from a ShipClassDef, then overwrite the
    dims/HP from its SHIP_TYPES entry (mirrors Carrier's override pattern) and
    pin the per-unit fire-control knobs.

    Subclasses set ``CLASS_DEF`` to their ShipClassDef.
    """

    CLASS_DEF: ShipClassDef = GENERAL_DESTROYER_DEF

    def __init__(self, ship_id, anchor_xz, heading_deg=0.0,
                 patrol_radius_m=8_000.0):
        cdef = self.CLASS_DEF
        super().__init__(
            ship_id, anchor_xz, heading_deg=heading_deg,
            patrol_radius_m=patrol_radius_m,
            sm2_ammo=cdef.sm2_ammo,
            ciws_ammo=cdef.ciws_ammo,
            tomahawk_ammo=cdef.tomahawk_ammo)
        # SM-6 is not a Destroyer ctor arg — set it explicitly (the base ctor
        # defaults it to _SM6_AMMO_DEFAULT, so a class with a different load
        # MUST override here).
        self.sm6_ammo = int(cdef.sm6_ammo)
        # Overwrite the ship-type-derived dims/HP from the class's SHIP_TYPES
        # entry (Carrier override pattern). For the general destroyer this is
        # the SAME "destroyer" entry, so the result is byte-identical.
        spec = SHIP_TYPES[cdef.ship_type]
        self.ship_type = cdef.ship_type
        self.length = spec["length"]
        self.beam = spec["beam"]
        self.height = spec["height"]
        self.speed = spec["speed"]
        self.hp = spec["hp"]
        # Ship.__init__ computed hit_reach from the BASE "destroyer" dims; now
        # that the dims may have changed (only the Flagship's do — AAW/Ground-
        # Attack reuse the destroyer hull), recompute the OBB bounding-sphere
        # reach with the SAME formula Ship.__init__ uses so damage.py's pair
        # prefilter (a conservative reject of any pair farther apart than the
        # sum of reaches) never under-reaches the true farthest OBB corner.
        # GeneralDestroyer keeps the destroyer dims, so this reproduces the
        # legacy value EXACTLY -> the byte-identical default is preserved.
        self.hit_reach = (0.5 * math.sqrt(
            self.beam ** 2 + (self.height + HULL_DRAFT) ** 2 + self.length ** 2)
            + 0.5 * (self.height - HULL_DRAFT))
        # Per-unit fire-control knobs (read via getattr with fallback by the
        # controller, so a plain Destroyer is unaffected).
        self.sm2_max_inflight = int(cdef.sm2_max_inflight)
        self._track_form_s = float(cdef.track_form_s)
        # DESCRIPTIVE/test-only flag (see module docstring): the world finds the
        # hub via isinstance(s, Flagship), NEVER by reading this attribute, so
        # the two never drift in any control path.
        self.is_datalink_hub = bool(cdef.is_datalink_hub)
        self.ship_class_role = cdef.role


class GeneralDestroyer(_ClassedDestroyer):
    """General-purpose escort — numerically identical to today's Destroyer.

    BYTE-IDENTICAL: ship_type stays "destroyer", every magazine/dim/HP matches
    the legacy Destroyer, so the default fleet (built from these) replays the
    legacy battle bit-for-bit.  The only additions are the inert getattr knobs
    (sm2_max_inflight == the LOCKED const, _track_form_s == TRACK_FORM_S,
    is_datalink_hub == False) which leave every controller path unchanged.
    """

    CLASS_DEF = GENERAL_DESTROYER_DEF


class AirDefenseShip(_ClassedDestroyer):
    """Dedicated air-defense escort: deep SM-2 magazine + higher concurrent
    cap; no land-attack.  Sustains more concurrent SM-2s in a raid."""

    CLASS_DEF = AIR_DEFENSE_DEF


class GroundAttackShip(_ClassedDestroyer):
    """Land-attack escort: a heavy TLAM bank that drains FIRST in a salvo."""

    CLASS_DEF = GROUND_ATTACK_DEF


class Flagship(_ClassedDestroyer):
    """CEC datalink-hub command ship.  is_datalink_hub=True — its live radar
    cues the escorts; the world drops it from the remote-cue set on death."""

    CLASS_DEF = FLAGSHIP_DEF
