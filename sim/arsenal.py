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
    eject_time: float        # s, catapult phase duration
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
    eject_speed=30.0, eject_time=0.6,
    motor_thrust=200_000.0, motor_time=12.0, isp=240.0,
    ref_area=0.208,    # pi * (0.515/2)^2
    max_g=25.0, fuse_radius=25.0,
    terminal_range=20_000.0, max_range=150_000.0,
    self_destruct_t=180.0, self_destruct_speed=250.0,
    min_intercept_alt=100.0, max_intercept_alt=25_000.0,
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

WEAPONS = {"oniks": ONIKS}
SAMS = {"s300": S300}
LAUNCHERS = {"bastion": BASTION, "s300_tel": S300_TEL}
