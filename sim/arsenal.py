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
    min_intercept_alt=30.0, max_intercept_alt=24_000.0,
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

WEAPONS = {"oniks": ONIKS}
SAMS = {"s300": S300, "sm2": SM2}
LAUNCHERS = {"bastion": BASTION, "s300_tel": S300_TEL, "sm2_vls": SM2_VLS}
