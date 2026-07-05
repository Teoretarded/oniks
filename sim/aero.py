"""Shared missile energy model: induced drag, q-limited g, autopilot lag.

NORMATIVE basis: docs/research/missile_energy_autopilot_2026-07-05.md.
Every flight machine (sim/missile.py Missile, sim/sam.py SamMissile,
sim/strike.py StrikeMissile) calls THESE functions — no per-machine copies
of the formulas (LOCKED, plan 2026-07-05). Pure scalar math, GL-free; each
function is a handful of mul/adds, safe per missile per 120 Hz substep.

The physics (research §2-§3):
  q       = 0.5 * rho(h) * V^2                        dynamic pressure
  n_avail = q * S * CLmax / (m * g)                   the aero g ceiling —
            at low speed / high altitude a missile CANNOT pull its rated g
  D_i     = k * L^2 / (q * S)                         induced drag: the turn
            tax, scaling with load factor SQUARED and 1/q
  a_dot   = (a_cmd - a) / tau                         three-loop autopilot
            modeled as a first-order lag (~0.3 s class)

Per-weapon overrides live on the arsenal defs (k_induced / cl_max /
autopilot_tau / thrust_tau, 0.0 = UNSET -> the class defaults below), so a
winged subsonic cruiser and a body-lift cruciform SAM pay honestly
different turn taxes.
"""

import math

from sim.physics import DENSITY_SCALE_HEIGHT, RHO0

# --- class defaults (research doc §5.2; per-weapon fields override) ----------

# Induced-drag factor K in CD = CD0 + K*CL^2. Cruciform body-lift missiles
# ~0.2 (research: "deliberately on the punishing side so hard turns hurt");
# genuinely WINGED airframes (Tomahawk/Kalibr/JASSM/SWARM) carry their lift
# far cheaper — set per-weapon (~0.035) on their defs.
K_INDUCED = 0.2

# CLmax on the body cross-section reference area. The research doc's 1.2 is
# a conservative slender-body value; agile fin-steered SAMs demonstrably
# reach far higher normal-force coefficients on this tiny reference (a
# Sidewinder pulling 30 g at Mach 2 works out to CL ~ 8 on cross-section).
# Class defaults anchor each machine's DESIGN point; per-weapon cl_max on
# the def is derived from its rated max_g at its design speed (arsenal
# comments show the arithmetic).
CL_MAX_CRUISE = 4.0     # Missile machine (Oniks-class anchor: 11 g @ M2 SL)
CL_MAX_SAM = 6.0        # SamMissile machine (mid-band anchor)
CL_MAX_STRIKE = 7.0     # StrikeMissile machine (winged cruisers)

# Autopilot (achieved-accel) first-order time constants, seconds.
AP_TAU_CRUISE = 0.4     # 3 t ramjet airframe (research: "larger/slower 0.4-0.6")
AP_TAU_SAM = 0.25       # interceptor class (research: "agile terminal 0.15-0.3")
AP_TAU_STRIKE = 0.5     # subsonic cruiser

# q*S floor for the induced-drag division (a near-stationary missile has no
# meaningful induced drag; the guidance stall fade already kills its lift).
QS_FLOOR = 1.0          # N


def q_scalar(speed: float, alt_m: float) -> float:
    """Dynamic pressure 0.5*rho*V^2 (exponential ISA atmosphere)."""
    rho = RHO0 * math.exp(-max(alt_m, 0.0) / DENSITY_SCALE_HEIGHT)
    return 0.5 * rho * speed * speed


def accel_limit_scalar(q: float, ref_area: float, mass: float,
                       cl_max: float) -> float:
    """Max aerodynamic lateral accel (m/s^2) the airframe can lift at this
    dynamic pressure: q*S*CLmax/m (research §3.4b)."""
    return q * ref_area * cl_max / mass


def induced_drag_scalar(lift_n: float, q: float, ref_area: float,
                        k_induced: float) -> float:
    """Induced drag (N) paid for generating ``lift_n`` of aerodynamic force:
    k*L^2/(q*S), q*S floored (research §2.2 'the turn tax')."""
    return k_induced * lift_n * lift_n / max(q * ref_area, QS_FLOOR)


def lag_gain(dt: float, tau: float) -> float:
    """First-order lag blend factor for one step (implicit-Euler form —
    unconditionally stable at any dt): a += (cmd - a) * lag_gain(dt, tau)."""
    return dt / (dt + tau)
