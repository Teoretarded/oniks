"""ESM decoy emitter + corner-reflector back-plot decoy data (pure numpy, GL-free).

M5 #5.  Two cheap PLAYER spoofers.  The HARD RULE (the honesty contract): the
enemy AI is fooled because its SENSORS are fooled — these plant REAL sensor
events, they NEVER edit the AI's decision, add a "miss" flag, or read/write truth.

DecoyEmitter
------------
A radiating object the enemy ESM genuinely hears.  It duck-types ``sim.radar.Radar``
(``.radar_id`` / ``.pos`` / ``.antenna_alt`` / ``.alive`` / ``.emitting`` /
``.detects()``) so it rides the SAME paths as the real radar station and the CBR:

  * ElintReceiver hears it and the enemy ``_feed_enemy_picture`` accrues a real
    ``EmitterIntel`` on its id (``commander.update_emitter``), so the commander's
    EXISTING ``_doctrine_blind`` schedules a HARM package at the located+alive
    decoy — the HARM is wasted on bait.  No commander code is touched.
  * It is BAIT, NOT a sensor: its detection ranges are EMPTY (``DECOY_RANGES``),
    so ``detects()`` returns False for every target — it never sees anything.

When a HARM kills the decoy Structure, the EXISTING HARM BDA path
(``mark_emitter_destroyed``) marks its ``EmitterIntel`` dead — no special case.

CornerReflector
---------------
A static false RF return planted near a fake coastal point.  It does NOT itself
emit; it BIASES the enemy's back-plot of a REAL player launch: when a real launch's
back-plotted surface point lands within the reflector's influence radius, an EXTRA
biased ``BackPlotEntry`` is injected (through the SAME ``add_back_plot`` path) that
is pulled toward the planted reflector XZ.  A ``LaunchCluster`` then forms on the
decoy coast and the enemy salvo refines onto empty ground — the real TEL survives.
This is a REAL false-return geometry, NOT a flag that tells the AI to miss.

``biased_back_plot`` is a PURE helper (no self / RNG / truth read): given the
first-seen sensor track + a reflector, it returns the (possibly) biased surface
back-plot, reusing the SHARED ``sim.commander.back_plot_surface`` so both sides of
the duel run one tested function.  With NO reflector in range it returns the
un-biased plot byte-for-byte (the regression seam).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from sim.commander import back_plot_surface


# --- Decoy emitter radar parameters ------------------------------------------
# EMPTY detection ranges: the decoy is BAIT, not a sensor.  ``Radar.detects()``
# looks up ``ranges.get(size_class, 0.0)`` -> 0.0 for every class -> the
# ``rng > max_range`` gate always rejects, so the decoy NEVER detects anything.
# (Mirrors the ELINT/EW pod beacons in sim/recon.py, which use ``ranges={}`` for
# exactly the same "radiates but never sees" duck-type.)
DECOY_RANGES: dict = {}

# A short mast: the decoy is a cheap ground emitter, not a tall warning set.  Its
# antenna height only sets the ELINT/ESM horizon datum (the functional-ESM feed
# in world/combat.py has no range gate, so the decoy is heard regardless — the
# height is here for duck-type parity + any future LOS-gated consumer).
DECOY_ANTENNA_M: float = 8.0

# Corner-reflector influence radius (m): a real player launch whose back-plotted
# surface point lands within this distance of the planted reflector gets pulled
# toward the reflector (a false RF return dominating the fix in that patch).
# Sized to the back-plot cluster radius so a reflector reliably captures launches
# whose honest back-plot already lands near the decoy coast point — the player
# plants it where the enemy WILL back-plot, and the bias finishes the deception.
CR_INFLUENCE_M: float = 8_000.0

# Bias strength (0..1): the fraction of the way from the honest back-plot toward
# the reflector the biased entry is placed.  1.0 == snap onto the reflector;
# below 1 leaves a little honest residue.  0.85 pulls the cluster decisively onto
# the decoy coast (well outside the real pad's SEEKER_BASKET) while keeping the
# planted return a believable NEAR-but-not-exact echo, not a teleport.
CR_BIAS_FRAC: float = 0.85


# --- DecoyEmitter -------------------------------------------------------------

class DecoyEmitter:
    """A radiating ESM decoy — heard by enemy ESM, detects nothing.

    Duck-types ``sim.radar.Radar`` for every attribute the ELINT receiver and the
    enemy emitter-accrual feed read (``radar_id`` / ``pos`` / ``antenna_alt`` /
    ``alive`` / ``emitting`` / ``detects``).  Built with EMPTY ranges so it is
    bait, never a sensor.
    """

    def __init__(self, radar_id: str, pos, antenna_m: float = DECOY_ANTENNA_M):
        self.radar_id = radar_id
        self.pos = np.asarray(pos, dtype=np.float64)
        self.antenna_m = float(antenna_m)
        self.ranges = dict(DECOY_RANGES)   # EMPTY -> never detects
        self.alive = True
        self.emitting = True

    @property
    def antenna_alt(self) -> float:
        return float(self.pos[1]) + self.antenna_m

    def detects(self, target_pos, size_class: str, jammers=()) -> bool:
        """ALWAYS False: a decoy emitter is bait, not a sensor.  Ranges are empty
        so ``ranges.get(size_class, 0.0)`` is 0.0 and any real target sits outside
        a zero-metre envelope.  Implemented explicitly (rather than leaning on the
        empty-dict lookup) so the contract is unmissable and a jammers kwarg is
        accepted for Radar signature parity."""
        return False


# --- CornerReflector ----------------------------------------------------------

@dataclass
class CornerReflector:
    """A static false RF return planted near a fake coastal point.

    It does NOT emit (no ESM signature of its own) — it biases the enemy back-plot
    of a REAL player launch toward its planted XZ.  ``influence_m`` is the radius
    inside which a real launch's honest back-plot is captured; ``bias_frac`` is how
    hard it is pulled toward the reflector.  Wrapped in a destructible Structure by
    the world (a HARM/TLAM into it is a satisfying waste).
    """

    reflector_id: str
    pos: np.ndarray                       # (3,) XYZ ground centre of the decoy point
    influence_m: float = CR_INFLUENCE_M
    bias_frac: float = CR_BIAS_FRAC
    alive: bool = field(default=True)

    def __post_init__(self):
        self.pos = np.asarray(self.pos, dtype=np.float64)

    @property
    def xz(self) -> tuple[float, float]:
        return (float(self.pos[0]), float(self.pos[2]))


# --- Pure back-plot bias helper ----------------------------------------------

def biased_back_plot(
    first_pos: np.ndarray,
    first_vel: np.ndarray,
    reflector: Optional[CornerReflector],
) -> Optional[tuple[float, float]]:
    """Back-plot a launch track to its surface point, biased toward a nearby
    corner reflector.

    PURE (no self / RNG / truth read).  Reuses the SHARED
    ``sim.commander.back_plot_surface`` so both sides of the duel run one tested
    function, then — if a LIVE reflector's planted XZ is within ``influence_m`` of
    the honest plot — returns a point pulled ``bias_frac`` of the way toward the
    reflector (an EXTRA / biased fix, a real false-return geometry).

    Returns the un-biased plot byte-for-byte when:
      * the honest back-plot is None (a dogleg the geometry cannot localize), OR
      * ``reflector`` is None / dead, OR
      * the honest plot is OUTSIDE the reflector's influence radius.
    So with no reflector in range the result is identical to the plain enemy
    back-plot — the byte-identical regression seam.
    """
    plot = back_plot_surface(first_pos, first_vel)
    if plot is None or reflector is None or not reflector.alive:
        return plot
    px, pz = plot
    rx, rz = reflector.xz
    dist = math.hypot(rx - px, rz - pz)
    if dist > reflector.influence_m:
        return plot
    frac = reflector.bias_frac
    return (px + (rx - px) * frac, pz + (rz - pz) * frac)
