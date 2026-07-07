"""Sea-clutter detection degradation (pure math, GL-free, no RNG).

NORMATIVE research: docs/research/sea_clutter.md (GIT σ⁰ shape, the
clutter-limited-vs-noise-limited argument, and the locked duel band).
Consumed by sim/radar.Radar.detects for size classes ``missile``/
``stealth`` below CLUTTER_ALT_M — a low target competes with the sea
return inside the same range–Doppler cells; a target above CLUTTER_ALT_M
separates cleanly in elevation and is untouched.

LOCKED identity (F3 conventions): ``sea_clutter_range_factor(3, ·) == 1.0``
EXACTLY — Douglas state 3 is today's implicit sea, so the default battle
is byte-identical by construction.  Calmer seas give no bonus: the legacy
detection ranges already assume a benign sea.
"""

from __future__ import annotations

CLUTTER_ALT_M = 100.0   # m: above this the target is out of the ridge

# Per-state peak range reduction at zero altitude (research doc: GIT-shaped
# spacing — slight->moderate costs little, rough states climb ~0.13/state,
# flattening toward phenomenal seas).  Floor 1 - 0.72 = 0.28 >= the locked
# 0.25 "never blinds" bound.
_REDUCTION = {4: 0.10, 5: 0.22, 6: 0.38, 7: 0.52, 8: 0.63, 9: 0.72}


def sea_clutter_range_factor(sea_state: int, target_alt_m: float) -> float:
    """Multiplier on a radar's max detection range for a LOW target in sea
    clutter.  1.0 exactly for states <= 3 (identity) and for any target at
    or above CLUTTER_ALT_M; bounded [0.28, 1.0] everywhere."""
    s = int(sea_state)
    if s <= 3:
        return 1.0
    alt = float(target_alt_m)
    if alt >= CLUTTER_ALT_M:
        return 1.0
    depth = 1.0 - max(alt, 0.0) / CLUTTER_ALT_M
    return 1.0 - _REDUCTION[min(s, 9)] * depth
