"""Destructible player base structures (pure numpy, GL-free).

Phase 3 (spec section 8): Bastion TELs, S-300 TELs and the player ground
radar station gain HP + destroyed states so the enemy commander's JASSM /
Tomahawk strikes can actually end the battle.

Axes per locked conventions: X = east, Y = up, Z = north.
All positions and dims in meters, float64.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from sim.damage import segment_hits_obb
from sim.missile import PH_DEAD

# --- Tuning constants (with justification) ------------------------------------

# Default HP per structure kind.
# - Bastion TEL: a 40-t vehicle with some ERA tiles; two Tomahawk/JASSM hits
#   are needed to mission-kill it (consistent with spec section 4.4 "all player
#   structures gain HP and destroyed states" — one hit leaves it burning but
#   still capable of a last salvo, second finishes it).
HP_BASTION_TEL: int = 2

# - S-300 TEL: same size/protection class as the Bastion TEL.
HP_S300_TEL: int = 2

# - Radar station: tall lattice tower with a radome — the tower structure is
#   light; any direct hit from a Tomahawk/JASSM kills it.  Matches spec
#   section 4.4 ("soft emitter") and the HARM targeting doctrine (one HARM
#   = one radar dead).
HP_RADAR_STATION: int = 1

# Default OBB dims (length, beam, height) in metres.
# - Bastion/S-300 TEL: based on the MAZ-543 / MZKT-7930 TEL chassis:
#     length ~14 m (cab + body), width ~3.3 m (fenders out to ~3.5 m),
#     height ~5–6 m to canister tops.  Rounded to (14, 3.5, 6).
DIMS_TEL: tuple[float, float, float] = (14.0, 3.5, 6.0)

# - Radar station: the models/structures.py slab is 12×12 m, the tower
#   reaches 1.2 + 7 + 7 + 3.4*2 = ~22.4 m.  OBB footprint stretched to
#   14×14 to cover the crew hut offset (~9 m east of centre) and the full
#   radome overhang; height 22 m matches the model top (segment_hits_obb
#   test: a missile at 15 m altitude crossing the footprint should hit).
DIMS_RADAR: tuple[float, float, float] = (14.0, 14.0, 22.0)

# Default HP table keyed on kind string.
_DEFAULT_HP: dict[str, int] = {
    "bastion_tel": HP_BASTION_TEL,
    "s300_tel": HP_S300_TEL,
    "radar_station": HP_RADAR_STATION,
}

# Default dims table keyed on kind string.
_DEFAULT_DIMS: dict[str, tuple[float, float, float]] = {
    "bastion_tel": DIMS_TEL,
    "s300_tel": DIMS_TEL,
    "radar_station": DIMS_RADAR,
}


# --- Structure ----------------------------------------------------------------

@dataclass
class Structure:
    """A destructible player base structure.

    Parameters
    ----------
    structure_id:
        Unique string identifier (e.g. "bastion_tel_00").
    kind:
        One of ``'bastion_tel'``, ``'s300_tel'``, ``'radar_station'``.
    pos:
        Ground centre in world space (float64 (3,), Y = terrain height).
    dims:
        OBB (length, beam, height) in metres.  If None the per-kind default
        from ``_DEFAULT_DIMS`` is used.
    hp:
        Initial hit-points.  If None the per-kind default is used.
    on_destroyed:
        Optional callback invoked **once** when the structure is killed:
        ``on_destroyed(structure)`` — used by the integration layer to clear
        ``Radar.alive`` when the radar-station structure is destroyed.
    """

    structure_id: str
    kind: str
    pos: np.ndarray            # float64 (3,) ground centre, +Y up
    dims: tuple[float, float, float] = None      # (length, beam, height) m
    hp: int = None
    alive: bool = field(default=True, init=False)
    on_destroyed: Optional[Callable[["Structure"], None]] = field(
        default=None, repr=False)

    def __post_init__(self):
        self.pos = np.asarray(self.pos, dtype=np.float64)
        if self.dims is None:
            self.dims = _DEFAULT_DIMS.get(self.kind, DIMS_TEL)
        if self.hp is None:
            self.hp = _DEFAULT_HP.get(self.kind, 1)

    def hit(self) -> None:
        """Decrement HP; mark dead and fire callback at 0."""
        if not self.alive:
            return
        self.hp -= 1
        if self.hp <= 0:
            self.hp = 0
            self.alive = False
            if self.on_destroyed is not None:
                self.on_destroyed(self)

    # --- OBB (axis-aligned: structures never move or rotate) ------------------

    def obb(self):
        """Axis-aligned OBB: (center(3,), half_extents(3,), identity3x3).

        Structures sit on the ground, so the box base is at pos[Y] and the
        top at pos[Y] + height.  The OBB centre is lifted by height/2 above
        pos so the slab-test helper sees a box centred at mid-height.
        """
        length, beam, height = self.dims
        half = np.array([length * 0.5, height * 0.5, beam * 0.5],
                        dtype=np.float64)
        # Centre at mid-height of the structure (Y floor = pos[1])
        center = self.pos + np.array([0.0, height * 0.5, 0.0],
                                     dtype=np.float64)
        rot = np.eye(3, dtype=np.float64)   # axis-aligned: no rotation
        return center, half, rot

    # Bounding sphere radius used by the prefilter in apply_missile_hits_structures.
    @property
    def hit_reach(self) -> float:
        length, beam, height = self.dims
        # half-diagonal of the OBB plus offset from pos to OBB centre
        return (0.5 * np.sqrt(length ** 2 + beam ** 2 + height ** 2)
                + height * 0.5)


# --- Bulk hit application ------------------------------------------------------

def apply_missile_hits_structures(
    missiles,
    structures: list[Structure],
    events: list,
) -> None:
    """Swept-segment OBB hit test: every live missile vs every live structure.

    Mirrors ``sim.damage.apply_missile_hits`` in pattern:
    - Conservative sphere prefilter before the OBB math.
    - On hit: missile dies (phase → PH_DEAD, impact_pos set), structure takes
      one hit, events get ``('base_hit', pos)`` and ``('base_destroyed', pos)``
      if hp reaches 0.
    - A missile is spent after one hit (break).

    Structures are static (no movement) so their OBBs are axis-aligned
    (identity rotation) and pre-computed once per call frame.
    """
    live_structs = []
    for s in structures:
        if not s.alive:
            continue
        center, half, rot = s.obb()
        live_structs.append((s, center, half, rot, s.hit_reach))
    if not live_structs:
        return

    for m in missiles:
        if not m.alive:
            continue
        mx, my, mz = float(m.pos[0]), float(m.pos[1]), float(m.pos[2])
        ppx, ppy, ppz = (float(m.prev_pos[0]), float(m.prev_pos[1]),
                         float(m.prev_pos[2]))
        # Segment length for prefilter
        seg = ((mx - ppx) ** 2 + (my - ppy) ** 2 + (mz - ppz) ** 2) ** 0.5

        for s, center, half, rot, reach in live_structs:
            if not s.alive:          # may have been killed by an earlier missile
                continue
            cx, cy, cz = float(center[0]), float(center[1]), float(center[2])
            dx = mx - cx
            dy = my - cy
            dz = mz - cz
            r = reach + seg
            if dx * dx + dy * dy + dz * dz > r * r:
                continue             # provably out of reach

            if not segment_hits_obb(m.prev_pos, m.pos, center, half, rot):
                continue

            impact = (m.prev_pos + m.pos) * 0.5
            m.alive = False
            m.phase = PH_DEAD
            m.impact_pos = impact.copy()

            was_alive = s.alive
            s.hit()
            events.append(("base_hit", impact.copy()))
            if was_alive and not s.alive:
                events.append(("base_destroyed", impact.copy()))
            break                    # missile spent
