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
    eject_speed: float       # m/s, cold-launch ejection speed
    eject_time: float        # s, duration of ejection phase
    booster_thrust: float    # N, solid booster
    booster_time: float      # s, booster burn duration
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
    eject_speed=30.0, eject_time=0.9,
    booster_thrust=410_000.0, booster_time=3.2,
    max_thrust=110_000.0, isp=1100.0,
    cruise_mach_hi=2.55, cruise_alt_hi=14_000.0, cruise_mach_lo=2.0, lo_alt=60.0,
    skim_alt=12.0, terminal_range=42_000.0,
    seeker_range=50_000.0, seeker_half_angle_deg=32.0,
    max_g=11.0, warhead_mass=250.0,
    ref_area=0.3526,   # pi * (0.67/2)^2
)


@dataclass(frozen=True)
class LauncherDef:
    launcher_id: str
    display_name: str
    weapon_ids: tuple
    reload_s: float


BASTION = LauncherDef("bastion", "Bastion-P TEL", ("oniks",), 18.0)

WEAPONS = {"oniks": ONIKS}
LAUNCHERS = {"bastion": BASTION}
