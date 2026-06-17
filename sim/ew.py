"""M3-F1 EW burn-through field model (pure math, GL-free, NO RNG).

The keystone of the electronic-warfare cluster: a barrage jammer raises a
victim radar's noise floor so a target is only detected ("burns through")
inside the burn-through / crossover range. Every later EW feature (Growler
entity, player ECM pod, home-on-jam seekers, ...) consumes this module.

Physics (open-source J/S geometry, two-way radar vs one-way jam):
  * the target echo at the receiver scales ~ 1 / R_target**4  (out AND back),
  * a barrage jammer's power at the receiver scales ~ 1 / R_jammer**2 (one way),
so the jammer dominates at long range and the target burns through up close.
Their ratio is

    J / S  =  EW_CAL * jam_power_w * R_target**4 / R_jammer**2

(a single lumped calibration constant rolls up the radar's reference echo
power, the jammer reference, antenna gains and bandwidth-mismatch factors —
it is *measured*, not guessed: see tools/probe_ew_burnthrough.py). The target
burns through where J/S crosses unity (0 dB):

    R_target**4 = R_jammer**2 / (EW_CAL * jam_power_w)
    burn_through_range = (R_jammer**2 / (EW_CAL * jam_power_w)) ** 0.25

This is a PURE, DETERMINISTIC function — outcomes emerge from geometry, never
a dice roll (the "physics not dice" contract). It is monotonic (a jammer
farther from the radar jams less, so the ring collapses less), continuous,
and floored close-in so a leaker that gets right on top of the radar is
ALWAYS detectable regardless of how loud the jammer is.

A jammer is duck-typed: any object with ``.pos`` (3,) and ``.jam_power_w``
(watts). The Growler / player-pod ENTITIES are later M3 features; this module
just takes such objects. A jammer with terrain masking its line of sight to
the radar contributes nothing (a screened emitter can't jam).
"""

from __future__ import annotations

import math

from sim.radar import terrain_blocks

# ---------------------------------------------------------------------------
# Named, commented constants. EW_CAL is LOCKED by the calibration probe
# (tools/probe_ew_burnthrough.py) — do NOT hand-tweak it; re-run the probe.
# ---------------------------------------------------------------------------

# Lumped J/S calibration constant (units 1 / (W * m**2), since J/S is
# dimensionless and the geometry term is R_t**4 / R_j**2 in m**2). Calibrated
# so the DEFAULT Growler-class jammer (EW_DEFAULT_JAM_POWER_W) at its DEFAULT
# standoff (EW_DEFAULT_STANDOFF_M) collapses the player station's 350 km ship
# ring to ~175 km (HALF — the spec's calibration target):
#     EW_CAL = R_j**2 / (jam_power_w * R_bt**4)
#            = 150000**2 / (200 * 175000**4) = 1.1995e-13  ->  rounded 1.2e-13.
# Probe run 2026-06-17 confirms the default case lands inside [165 km,185 km].
EW_CAL: float = 1.2e-13

# Close-in detection floor (m): a target inside this ground range from the
# radar is ALWAYS detectable (range-gate-wise) no matter how loud or near the
# jammer — a leaker that reaches knife range cannot be hidden by noise jamming.
# Below the ~30 km point-defence horizon so it never masks a real engagement.
EW_CLOSE_FLOOR_M: float = 8_000.0

# Representative DEFAULT Growler-class barrage jammer (used by the calibration
# probe + test; the real ENTITY arrives in a later M3 feature). 200 W of
# effective in-band barrage power is a deliberately round game-balance figure,
# not an ELINT datum — a physics reviewer should re-measure against the real
# pod once the Growler entity exists.
EW_DEFAULT_JAM_POWER_W: float = 200.0
EW_DEFAULT_STANDOFF_M: float = 150_000.0   # behind the threat screen
EW_DEFAULT_JAMMER_ALT_M: float = 12_000.0  # standoff orbit altitude (clears horizon)


def _ground_range(a, b) -> float:
    """Horizontal (x,z) range in meters between two (x, y, z) points."""
    dx = float(b[0]) - float(a[0])
    dz = float(b[2]) - float(a[2])
    return math.hypot(dx, dz)


def js_db(radar_pos, target_pos, jammer) -> float:
    """Jam-to-signal ratio in dB at ``radar_pos`` for ``target_pos`` against
    ``jammer``.  J/S = EW_CAL * jam_power_w * R_t**4 / R_j**2.

    > 0 dB  => the jammer dominates (target hidden, long of burn-through).
    < 0 dB  => the target burns through (short of burn-through).
    Pure geometry; no RNG. A target/jammer at zero range is clamped to a tiny
    epsilon so the log is finite (the close-in floor governs detection there).
    """
    r_t = max(_ground_range(radar_pos, target_pos), 1e-6)
    r_j = max(_ground_range(radar_pos, jammer.pos), 1e-6)
    jam_power = max(float(jammer.jam_power_w), 0.0)
    js_lin = EW_CAL * jam_power * (r_t ** 4) / (r_j ** 2)
    if js_lin <= 0.0:
        return float("-inf")
    return 10.0 * math.log10(js_lin)


def _single_burn_through(radar_pos, jammer) -> float:
    """Burn-through range (m) for ONE jammer: the R_target at which J/S == 1.
    Larger jammer standoff (R_j) -> larger burn-through (weaker jam)."""
    r_j = max(_ground_range(radar_pos, jammer.pos), 1e-6)
    jam_power = max(float(jammer.jam_power_w), 0.0)
    if jam_power <= 0.0 or EW_CAL <= 0.0:
        return float("inf")  # a silent/zero-power jammer never collapses the ring
    return (r_j ** 2 / (EW_CAL * jam_power)) ** 0.25


def burn_through_range(radar, target_pos, jammers, height_fn=None) -> float:
    """Meters: the R_target at which the target burns through the LOUDEST
    jammer (smallest burn-through). MIN over all jammers that actually have
    line of sight to the radar — a terrain-masked jammer is dropped.

    ``target_pos`` is accepted for interface symmetry (the crossover range is
    a property of the radar+jammer geometry, not the target's current range).
    ``radar`` exposes ``.pos`` (site) and ``.antenna_alt`` (mast top); LOS is
    tested from the jammer to the radar antenna. With no effective jammer the
    ring is unchanged, so we return the radar's max ship-class-agnostic max:
    callers clamp against ``radar.ranges`` themselves. Here "no jammer" yields
    +inf which ``effective_range`` clamps to the radar max.
    """
    rax, raz = float(radar.pos[0]), float(radar.pos[2])
    ra_alt = float(radar.antenna_alt)
    radar_ant = (rax, ra_alt, raz)

    best = float("inf")
    for jam in jammers:
        # LOS gate: a jammer screened from the radar by terrain can't jam.
        jpos = (float(jam.pos[0]), float(jam.pos[1]), float(jam.pos[2]))
        if height_fn is None:
            masked = terrain_blocks(jpos, radar_ant)
        else:
            masked = terrain_blocks(jpos, radar_ant, height_fn=height_fn)
        if masked:
            continue
        bt = _single_burn_through(radar.pos, jam)
        if bt < best:
            best = bt
    return best


def effective_range(radar, size_class: str, target_pos, jammers,
                    height_fn=None) -> float:
    """Effective max detection range (m) for ``size_class`` under jamming.

    REGRESSION GATE: when ``jammers`` is empty this returns
    ``radar.ranges.get(size_class, 0.0)`` IDENTICALLY (byte-for-byte the
    legacy lookup) so the no-jammer path never changes one bit.

    Otherwise: ``max(EW_CLOSE_FLOOR_M, min(radar_max, burn_through_range))``
    — monotonic + continuous, with a close-in floor so a leaker that reaches
    knife range is always detectable.
    """
    radar_max = radar.ranges.get(size_class, 0.0)
    if not jammers:
        return radar_max
    bt = burn_through_range(radar, target_pos, jammers, height_fn=height_fn)
    collapsed = min(radar_max, bt)
    return max(EW_CLOSE_FLOOR_M, collapsed)
