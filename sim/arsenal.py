"""Data-driven weapon and launcher definitions (pure data, GL-free).

All dimensions SI (meters, kilograms, seconds, newtons); angles in degrees
only for config constants suffixed _deg.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class WeaponDef:
    weapon_id: str
    display_name: str
    length: float            # m
    diameter: float          # m
    launch_mass: float       # kg, total at launch
    fuel_mass: float         # kg, ramjet fuel (excludes booster)
    eject_speed: float       # m/s, tube-exit speed (hot ride-out, Task LC)
    eject_time: float        # s, IGNITION beat: in-tube + muzzle-clear time
    booster_thrust: float    # N, solid booster HIGH-thrust mode
    booster_time: float      # s, high-thrust burn cap (burnout is at Mach 2)
    max_thrust: float        # N, ramjet max thrust
    isp: float               # s, ramjet specific impulse
    cruise_mach_hi: float    # cruise Mach on the hi-altitude profile
    cruise_alt_hi: float     # m, hi-profile cruise altitude
    cruise_mach_lo: float    # cruise Mach on the lo-altitude profile
    lo_alt: float            # m, lo-profile cruise altitude
    skim_alt: float          # m, terminal sea-skim altitude
    terminal_range: float    # m, range-to-target at which terminal phase starts
    seeker_range: float      # m, active seeker acquisition range
    seeker_half_angle_deg: float  # deg, seeker gimbal half-angle
    max_g: float             # max lateral acceleration in g
    warhead_mass: float      # kg
    ref_area: float          # m^2, aerodynamic reference area


ONIKS = WeaponDef(
    weapon_id="oniks", display_name="P-800 Oniks",
    length=8.9, diameter=0.67, launch_mass=3000.0, fuel_mass=780.0,
    eject_speed=30.0, eject_time=0.35,
    booster_thrust=300_000.0, booster_time=9.5,
    max_thrust=110_000.0, isp=1100.0,
    cruise_mach_hi=2.55, cruise_alt_hi=14_000.0, cruise_mach_lo=2.0, lo_alt=60.0,
    skim_alt=12.0, terminal_range=42_000.0,
    seeker_range=50_000.0, seeker_half_angle_deg=32.0,
    max_g=11.0, warhead_mass=250.0,
    ref_area=0.3526,   # pi * (0.67/2)^2
)


@dataclass(frozen=True)
class SamDef:
    """Surface-to-air interceptor definition (Task S2). A separate type from
    WeaponDef on purpose: a SAM's flight regime (catapult eject, short solid
    boost, unpowered midcourse coast, proximity fuse) shares almost no fields
    with the ramjet cruise missile — shoehorning both into one dataclass
    would leave most fields meaningless for one of them."""
    weapon_id: str
    display_name: str
    length: float            # m
    diameter: float          # m
    launch_mass: float       # kg, total at launch
    propellant_mass: float   # kg, solid propellant
    eject_speed: float       # m/s, catapult cold-launch speed (vertical)
    eject_time: float        # s, unlit ballistic hang before motor ignition
    motor_thrust: float      # N, solid motor
    motor_time: float        # s, nominal burn (= propellant_mass / mdot)
    isp: float               # s; mdot = motor_thrust / (isp * 9.81)
    ref_area: float          # m^2, aerodynamic reference area
    max_g: float             # max lateral acceleration in g
    fuse_radius: float       # m, proximity fuse kill radius
    terminal_range: float    # m, range at which terminal PN takes over
    max_range: float         # m, max guided range vs air (launch gate / ring)
    self_destruct_t: float   # s, flight-time self-destruct
    self_destruct_speed: float  # m/s, post-burnout minimum speed
    min_intercept_alt: float    # m, engagement envelope floor
    max_intercept_alt: float    # m, engagement envelope ceiling


S300 = SamDef(
    weapon_id="s300", display_name="S-300 48N6",
    length=7.5, diameter=0.515, launch_mass=1900.0, propellant_mass=1020.0,
    # Task LC true cold launch (s300_reference.md §1): catapult exit, pure
    # ballistic hang to near-zero vertical speed ~20-25 m above ground,
    # delay-unit ignition 1.5 s after tube exit. The pause is sacred.
    eject_speed=18.0, eject_time=1.5,
    motor_thrust=200_000.0, motor_time=12.0, isp=240.0,
    ref_area=0.208,    # pi * (0.515/2)^2
    max_g=25.0, fuse_radius=25.0,
    terminal_range=20_000.0, max_range=150_000.0,
    self_destruct_t=180.0, self_destruct_speed=250.0,
    min_intercept_alt=100.0, max_intercept_alt=25_000.0,
)

# SM-2 Block IIIB / Mk 41 VLS — ship-launched interceptor
# --------------------------------------------------------
# Derivation notes (calibrated against S-300 as reference):
#   Real SM-2ER: mass ~1340 kg, 4-fin, Mach 3.5 class, ~150 km range.
#   Motor: we need the missile to reach ≥Mach 3.5 and fly ~150 km.
#   S-300 calibration: 200 000 N thrust, 1900 kg, 12 s burn →
#     burnout at ~Mach 5.2; that gives a 150 km coast because it leaves
#     boost at high speed + high alt. SM-2 is lighter (1340 kg) but its
#     single-stage motor must also coast the 150 km at Mach 3.5 cruise.
#   Working backward from a lofted 150 km shot needing ~120 s total:
#     thrust = 130 000 N, burn = 15 s, isp = 240 s (same propellant type).
#     mdot = 130 000 / (240 * 9.81) = 55.2 kg/s; 15 s consumes 828 kg ≈
#     propellant_mass 830 kg (confirmed: leaves 510 kg structural + seeker).
#     Burnout Mach (sea level): delta-v ~ thrust*burn/avg_mass ~1780 m/s →
#     Mach ≈ 5.2 at burnout alt (~4 km) then decelerates coasting to
#     terminal at Mach ~3.5, consistent with the real SM-2 cruise Mach.
#   VLS eject: Mk 41 cold-launch gas ejector pops the round 10-20 m clear
#     of the deck at ~20 m/s in ~0.5 s, then the motor lights immediately.
#     eject_time = 0.5 s (much shorter than S-300's 1.5 s hanging hang;
#     the deck ejector is a brief gas pulse, not a ballistic free-flight).
SM2 = SamDef(
    weapon_id="sm2", display_name="SM-2 Block IIIB",
    length=6.55, diameter=0.343, launch_mass=1340.0, propellant_mass=830.0,
    # VLS cold-gas eject: ~20 m/s deck-clear in 0.5 s, motor lights instantly.
    eject_speed=20.0, eject_time=0.5,
    motor_thrust=130_000.0, motor_time=15.0, isp=240.0,
    ref_area=0.0924,   # pi * (0.343/2)^2
    max_g=25.0, fuse_radius=20.0,
    terminal_range=20_000.0, max_range=150_000.0,
    self_destruct_t=180.0, self_destruct_speed=250.0,
    # Engagement floor 25 m: real Aegis engages sea-skimmers all the way
    # down to the wavetops — there is no altitude at which the ship simply
    # refuses to shoot. What keeps the spec's profile contract ("lo-lo
    # becomes king", §5.2) is PHYSICS, not this gate: below MULTIPATH_ALT_M
    # (sim/sam.py) the position the SM-2 guides on carries low-elevation
    # multipath noise, so sea-skim shots miss often while hi flyers stay
    # near-certain kills. Statistical contract (supersedes the old
    # floor-justification regression): tests/test_sm2_statistics.py —
    # hi batch kill >= 0.75, lo batch within [0.2, 0.65].
    min_intercept_alt=25.0, max_intercept_alt=24_000.0,
)


@dataclass(frozen=True)
class LauncherDef:
    launcher_id: str
    display_name: str
    weapon_ids: tuple
    reload_s: float
    tubes: int = 1           # launch tubes / canisters on the TEL
    ammo: int = 0            # rounds carried; 0 = untracked (v1 Bastion)


BASTION = LauncherDef("bastion", "Bastion-P TEL", ("oniks",), 18.0)
S300_TEL = LauncherDef("s300_tel", "5P85 TEL", ("s300",), 8.0,
                       tubes=4, ammo=4)
# Mk 41 VLS cell on an Arleigh Burke: 90-cell magazine, each SM-2 occupies
# one cell; reload at sea is not modelled (finite stock, no reload timer).
SM2_VLS = LauncherDef("sm2_vls", "Mk 41 VLS", ("sm2",), 0.0,
                      tubes=8, ammo=24)

@dataclass(frozen=True)
class StrikeDef:
    """Land-attack / anti-radiation strike missile definition.

    Covers Tomahawk-class VLS cruise missiles, JASSM-class air-launched
    cruise missiles, and HARM-class anti-radiation missiles.  Fields
    deliberately parallel WeaponDef where the physics are shared (drag,
    mass, ref_area, isp/fuel, max_g) and diverge where they are not
    (no ramjet cruise_mach split, no seeker fields needed by the base
    class — HARM subclass has its own homing logic).
    """
    weapon_id: str
    display_name: str
    length: float               # m
    diameter: float             # m
    launch_mass: float          # kg, total at launch including booster if any
    fuel_mass: float            # kg, propellant consumed in flight
    booster_thrust: float       # N, booster / solid motor (0 = no booster)
    booster_time: float         # s, booster burn duration (0 = none)
    eject_speed: float          # m/s, speed at start of free guidance (VLS =
    #                             vertical eject; air-drop = release speed)
    eject_time: float           # s, eject / free-fall phase before motor
    max_thrust: float           # N, cruise thrust (turbofan / motor sustainer)
    isp: float                  # s, specific impulse for cruise phase
    cruise_mach: float          # target cruise Mach number
    cruise_alt: float           # m, commanded cruise altitude (AGL = above
    #                             local surface via surface_height_at)
    max_range: float            # m, maximum effective guided range (fuel gate)
    ref_area: float             # m^2, aerodynamic reference area
    max_g: float                # max lateral acceleration in g
    warhead_mass: float         # kg
    fuse_radius: float          # m, proximity fuse kill radius (HARM / default)


# --- Tomahawk BGM-109 (ship-launched VLS, land-attack) -----------------------
# Reference: BGM-109C/D Block IV (TLAM), open-source unclassified data.
#   Length: 6.25 m body + 0.52 m booster = 6.25 m cited (body only used here;
#     booster is jettisoned).  Game model uses the body length for rendering.
#   Launch mass with booster: ~1,440 kg.  Body-only mass ~1,000 kg post-boost.
#   Turbofan: Williams F107-WR-402, thrust ~3,100 N (272 kg-f), Isp ~3,600 s
#     (fuel-specific, very efficient turbofan — 100 kg JP fuel for 1,600 km).
#   Cruise Mach 0.74 (~250 m/s at sea level), cruise alt 30–50 m terrain-
#     following (game spec §9: 30–50 m cruise; using 50 m as commanded value).
#   VLS cold-gas eject: pops round at ~10 m/s, solid booster lights (12 s)
#     to push to cruise speed before booster jettison.  Booster thrust
#     ~44,500 N (estimated from 13 s to Mach 0.7 from rest, ~1,100 kg avg mass).
#   Max range: ~1,600 km real; game uses "effectively whole-map" → 2,000 km.
#   Fuel mass: sufficient to fly the whole map at Mach 0.74; isp is chosen so
#     2,000 km burns ~100 kg of fuel at Mach 0.74 (real TLAM fuel budget).
#     At 250 m/s, 2,000 km takes 8,000 s.  Thrust ≈ drag ≈ 1,200 N in cruise.
#     mdot = 1,200 / (3,600 * 9.81) = 0.034 kg/s → 8,000 s = 272 kg fuel.
#     Using 300 kg fuel for margin.
TOMAHAWK = StrikeDef(
    weapon_id="tomahawk", display_name="BGM-109 Tomahawk",
    length=6.25, diameter=0.527,
    launch_mass=1_440.0,   # kg with booster (unclassified cited figure)
    fuel_mass=300.0,       # kg JP-10 turbofan fuel for ~2,000 km at Mach 0.74
    # VLS booster: solid rocket pops round to cruise speed (~Mach 0.74) in 12 s.
    # Thrust estimated: 1,300 kg avg mass, 0-to-250 m/s in 12 s → ~27,000 N net.
    # With drag at ~Mach 0.3 avg (≈500 N), gross thrust ≈ 27,500 N.
    booster_thrust=27_500.0,   # N solid booster
    booster_time=12.0,         # s booster burn (game spec §5.2: "12 s")
    eject_speed=10.0,          # m/s VLS cold-gas eject speed
    eject_time=0.5,            # s from eject until booster ignition
    # Williams F107 turbofan in cruise.  3,100 N, Isp ≈ 3,600 s (thermodynamic
    # estimate for a small turbofan at Mach 0.74 — consistent with 100 kg/1,600 km)
    max_thrust=3_100.0,    # N turbofan cruise thrust
    isp=3_600.0,           # s specific impulse (turbofan — very high, fuel-efficient)
    cruise_mach=0.74,      # Mach, subsonic cruise (game spec §9)
    cruise_alt=50.0,       # m above local surface (game spec §9: 30–50 m, using 50)
    max_range=2_000_000.0, # m, effectively whole-map (game spec §9)
    ref_area=0.218,        # m^2 = pi * (0.527/2)^2
    max_g=4.0,             # g, terrain-following cruise missile maneuvering cap
    warhead_mass=450.0,    # kg conventional unitary warhead (TLAM-C cited)
    fuse_radius=5.0,       # m (impact fuze — hits ground; not a proximity weapon)
)

# --- AGM-158 JASSM (air-launched standoff land-attack) -----------------------
# Reference: AGM-158A JASSM, open-source unclassified data.
#   Length: 4.27 m.  Launch mass: ~1,020 kg.
#   Propulsion: Teledyne-Continental J402 turbojet, ~3,200 N, Isp ≈ 2,200 s
#     (subsonic turbojet — less efficient than turbofan).
#   Cruise Mach ~0.8 (~272 m/s sea level), cruise alt ~30 m terrain-following.
#   Range: 370 km (game spec §9 uses AGM-158A value).
#   Air-launched: fighter drops at typical 8 km ASL, 200-250 m/s; missile
#     free-falls 1 s then the motor ignites.
#   Fuel mass: 370 km at 272 m/s = 1,360 s; drag in cruise ≈ 1,500 N
#     (heavier / less slender than TLAM); mdot = 1,500/(2,200*9.81) = 0.069 kg/s
#     → 94 kg fuel for 370 km.  Using 100 kg for margin.
JASSM = StrikeDef(
    weapon_id="jassm", display_name="AGM-158 JASSM",
    length=4.27, diameter=0.45,
    launch_mass=1_020.0,   # kg (cited: ~1,020 kg)
    fuel_mass=100.0,       # kg JP fuel for 370 km at Mach 0.8
    # No booster: air-launched, drops cleanly then ignites.
    booster_thrust=0.0,
    booster_time=0.0,
    eject_speed=0.0,       # inherited from aircraft release velocity
    eject_time=1.0,        # s free-fall before motor ignition (game spec §5.1)
    # J402-CA-702 turbojet: ~3,200 N, Isp ≈ 2,200 s (subsonic jet)
    max_thrust=3_200.0,    # N
    isp=2_200.0,           # s
    cruise_mach=0.80,      # game spec §9
    cruise_alt=30.0,       # m AGL (game spec §9)
    max_range=370_000.0,   # m (game spec §9: 370 km)
    ref_area=0.159,        # m^2 = pi * (0.45/2)^2
    max_g=4.0,             # g cruise maneuvering cap
    warhead_mass=109.0,    # kg WDU-42/B penetrating warhead (cited)
    fuse_radius=5.0,       # m (impact fuze)
)

# --- AGM-88 HARM (air-launched anti-radiation) --------------------------------
# Reference: AGM-88C HARM, open-source unclassified data.
#   Length: 4.17 m.  Launch mass: ~361 kg.
#   Propulsion: Thiokol/Hercules SR113-TC-1 dual-thrust solid motor.
#     Boost phase: ~74,000 N for ~2.6 s (estimated from Mach 2+ in 3 s).
#     Sustain phase: ~6,000 N for ~35 s (typical dual-thrust HARM motor data).
#     Combined Isp ≈ 200 s (solid rocket, modest but typical for a small motor).
#   Cruise Mach 2+ (game spec §9: Mach 2.0; real is ~2.5; using 2.0 as tuned).
#   Loft profile: climbs to ~9 km, homes on emitting radar with PN.
#   Range: 110 km (game spec §9).
#   Proximity fuse radius: 15 m (game spec §8 "HARM" section).
#   Fuel mass: solid propellant — total burn is ~38 s.
#     mdot_boost = 74,000 / (200*9.81) = 37.7 kg/s for 2.6 s → 98 kg
#     mdot_sustain = 6,000 / (200*9.81) = 3.06 kg/s for 35 s → 107 kg
#     Total propellant: ~205 kg.  Round to 200 kg.
HARM = StrikeDef(
    weapon_id="harm", display_name="AGM-88 HARM",
    length=4.17, diameter=0.254,
    launch_mass=361.0,     # kg (cited: 361 kg)
    fuel_mass=200.0,       # kg solid propellant (boost + sustain phases)
    # Boost phase: very high thrust for 2–3 s to accelerate to Mach 2+.
    booster_thrust=74_000.0,  # N estimated from 0-to-Mach2 in ~3 s, ~300 kg avg mass
    booster_time=3.0,         # s boost phase duration
    eject_speed=0.0,       # air-launched: inherits aircraft release velocity
    eject_time=0.2,        # s free-fall before motor ignition (brief separation)
    # Sustain phase maintains speed against drag.
    max_thrust=6_000.0,    # N sustain thrust
    isp=200.0,             # s solid rocket Isp
    cruise_mach=2.0,       # game spec §9 (real ~2.5; tuned per spec)
    # HARM loft: commanded altitude 9,000 m (game spec: "lofts to ~9 km").
    cruise_alt=9_000.0,    # m loft altitude
    max_range=110_000.0,   # m (game spec §9: 110 km)
    ref_area=0.0507,       # m^2 = pi * (0.254/2)^2
    max_g=15.0,            # g, agile anti-radiation seeker head
    warhead_mass=66.0,     # kg WDU-21/B fragmentation warhead (cited)
    fuse_radius=15.0,      # m proximity fuse (game spec §8: "proximity 15 m")
)

WEAPONS = {"oniks": ONIKS}
SAMS = {"s300": S300, "sm2": SM2}
STRIKES = {"tomahawk": TOMAHAWK, "jassm": JASSM, "harm": HARM}
LAUNCHERS = {"bastion": BASTION, "s300_tel": S300_TEL, "sm2_vls": SM2_VLS}
