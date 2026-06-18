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


# 3M22 Zircon - hypersonic anti-ship (player). Reuses the Oniks Missile flight
# machine; the scramjet sustainer holds a hypersonic cruise, so it out-speeds the
# SM-2 reaction window even on a high profile (the "break the screen" round).
ZIRCON = WeaponDef(
    weapon_id="zircon", display_name="3M22 Zircon",
    length=9.0, diameter=0.70, launch_mass=3400.0, fuel_mass=900.0,
    eject_speed=30.0, eject_time=0.35,
    booster_thrust=360_000.0, booster_time=11.0,
    max_thrust=200_000.0, isp=1300.0,
    # Fast medium-altitude cruise (not a 28 km lofter: the shared descent gains,
    # tuned for the M2.5 Oniks, cannot bleed 28 km at M5+, so a high lofter
    # overshoots. 14 km + an early 100 km terminal handover lets the hypersonic
    # dive capture in time — the SPEED, not the apogee, is the Zircon's edge).
    cruise_mach_hi=8.0, cruise_alt_hi=14_000.0, cruise_mach_lo=4.5, lo_alt=80.0,
    skim_alt=15.0, terminal_range=100_000.0,
    seeker_range=60_000.0, seeker_half_angle_deg=30.0,
    max_g=14.0, warhead_mass=300.0,
    ref_area=0.3848,   # pi * (0.70/2)^2
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
    # Loft / energy-management arc shaping — read PER ROUND by
    # sim.sam._aim_direction so different rounds fly DIFFERENT arcs (the 48N6
    # medium loft vs the 40N6 high loft).  Commanded midcourse altitude sits
    # ``loft_gain`` m above the aim point per m of ground range-to-go beyond
    # ``loft_fade_range``, capped at ``loft_bias_max``; inside the fade range
    # the bias is zero, so the dive onto the real target is established before
    # terminal PN takes over.  Defaults = the baseline medium-loft profile
    # (48N6 / SM-2 / SM-6 / Pantsir; tuned by sweep, see sim/sam.py loft note);
    # only the 40N6 overrides them for its high lofted long-range trajectory.
    loft_gain: float = 0.55             # m of altitude bias per m of range-to-go
    loft_bias_max: float = 14_000.0     # m, peak loft above the aim point
    loft_fade_range: float = 25_000.0   # m, range-to-go below which loft -> 0


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

# --- Kh-31P (player anti-radiation, M2-T2) ------------------------------------
# Reference: Kh-31P (Zvezda-Strela), open-source unclassified data.
#   The PLAYER counterpart to the enemy AGM-88 HARM: a passive-radar-homing
#   SEAD round.  Reuses the HarmMissile flight/homing machine VERBATIM (it
#   loft-climbs, PN-homes on an emitting sim.radar.Radar, draws the seeded
#   silence-CEP miss ring on radar silence, re-locks on re-emit).  This def is
#   a StrikeDef like HARM; the only behavioural difference is is_hostile=False
#   (PlayerArmMissile subclass — see sim/strike.py).
#
#   Real Kh-31P figures (open sources):
#     Length 4.7 m, diameter 0.36 m, launch mass ~600 kg, warhead ~87 kg.
#     Propulsion: solid BOOSTER cartridge (burns inside the ramjet duct) then
#       a kerosene RAMJET sustainer to ~Mach 3.  Stated range ~110 km (later
#       Kh-31PD ~250 km; we model the classic ~110 km round per the spec).
#     Passive radar seeker (L-111E family), homes on emitting SAM/EW radars.
#
#   TUNING (measured with tools/probe_kh31p_flyoff.py — MEASURE FIRST, never
#   assume the airframe behaves).  CRITICAL airframe finding: the reused
#   HarmMissile flight model's altitude-hold gains (CRUISE_ALT_* in
#   sim/strike.py) are tuned for the subsonic-to-Mach-2 HARM/Tomahawk regime
#   and CANNOT arrest a Mach-3 round's climb — at any cruise_alt the round
#   zoom-climbs to ~15 km, then the lofted glide carries it far.  (The
#   existing HARM exhibits the SAME behaviour: it apogees ~19 km and kills out
#   past 160 km in a flyoff — its 110 km "max_range" is a nominal label, not a
#   measured flyoff gate.)  Changing the shared gains would alter HARM /
#   Tomahawk / JASSM flight (a regression), so they are LEFT ALONE and the
#   KH31P envelope is whatever this airframe HONESTLY produces.
#
#   The achievable two-sided envelope (NOT the textbook 110 km) — measured by
#   the probe at seed [1337, 8], stationary EMITTING radar:
#       range  peak Mach  cruise Mach   closest    result
#        60 km    2.94       2.80          11 m     HIT
#        90 km    2.94       2.80          12 m     HIT   <- locked KILL range
#       110 km    2.97       2.82          11 m     HIT   (also a clean kill)
#       130 km    2.98       2.84          11 m     HIT
#       140 km    2.98       2.84        1022 m     MISS  <- locked SHORT range
#     Cruise Mach >= 2.80 (meets the >= ~2.8 target); a clean two-sided gate:
#     kills out to 130 km, fuel/range-limited (falls short) at 140 km.  The
#     classic 110 km figure is exceeded on this glide-heavy machine — the
#     env test is locked to the MEASURED kill (90 km) and short (140 km).
#     (Long ToF — ~200 s at 110 km — is the lofted-glide signature inherent
#     to the shared flight model; the same applies to the in-game HARM.)
#
#   Propulsion model + budget (mirrors the HARM/Oniks fields):
#     booster (solid cartridge): 63,000 N for 3.0 s spikes the round to the
#       ramjet take-over speed off the rail.  At isp 950 s the booster grain
#       is mdot = 63,000/(950*9.81) = 6.76 kg/s -> 3 s = ~20 kg of the budget.
#     ramjet sustain: 9,000 N holds the Mach-3 cruise against drag; the
#       remaining ~43 kg of the 63 kg fuel budget is the powered-cruise reserve
#       and the RANGE GATE (kills to 130 km, short at 140 km).  isp 950 s is
#       the air-breathing ramjet value (cf. Oniks 1100 s) — solid-booster grain
#       is the small first slice, the kerosene ramjet is the rest.
KH31P = StrikeDef(
    weapon_id="kh31p", display_name="Kh-31P",
    length=4.7, diameter=0.36,
    launch_mass=600.0,     # kg (cited launch mass ~600 kg)
    fuel_mass=63.0,        # kg (booster grain + ramjet kerosene; probe-tuned)
    # Solid booster cartridge: high thrust off the rail to ramjet take-over
    # speed in ~3 s, then the ramjet duct sustains.
    booster_thrust=63_000.0,   # N (probe-tuned boost spike)
    booster_time=3.0,          # s booster burn
    eject_speed=0.0,       # air-launched: inherits aircraft release velocity
    eject_time=0.2,        # s brief free-fall before motor ignition
    # RAMJET sustain: air-breathing, so isp is high (cf. Oniks ramjet 1100 s).
    # Sustain thrust holds the Mach-3 cruise against drag; the fuel budget is
    # the range gate (kills to 130 km, falls short at 140 km — see table above).
    max_thrust=9_000.0,    # N ramjet sustain thrust (probe-tuned)
    isp=950.0,             # s ramjet-dominated specific impulse (air-breathing)
    cruise_mach=3.0,       # Mach ~3 ramjet cruise (real Kh-31P figure)
    # Loft profile: a low loft (3.5 km commanded) keeps the zoom-climb from
    # overshooting as far; the reused HarmMissile loft+PN geometry still works.
    cruise_alt=3_500.0,    # m commanded loft altitude (round zooms to ~15 km)
    max_range=130_000.0,   # m (MEASURED kill reach on this airframe; the
    #                        classic 110 km spec is exceeded — see table above)
    ref_area=0.1018,       # m^2 = pi * (0.36/2)^2
    max_g=15.0,            # g, agile anti-radiation seeker head (= HARM)
    warhead_mass=87.0,     # kg (cited Kh-31P warhead)
    fuse_radius=12.0,      # m proximity fuse (slightly tighter than HARM's 15 m)
)

# --- 40N6-class very-long-range SAM (player, Phase 5) -------------------------
# Derivation from the 48N6 (S300) as reference platform:
#
#   Real 40N6: ~400 kg warhead, ~4,000 kg launch mass, Mach 6+ boost,
#   max range ~380 km vs HIGH-altitude targets.  The ACTIVE terminal seeker
#   (ARH) means the launcher needs NO illuminator after launch — the missile
#   homes on its own RF return in terminal phase.  This is the key
#   discriminator vs the 48N6 (SARH).  The tradeoff: the active seeker has
#   difficulty discriminating low-altitude clutter returns, so the engagement
#   envelope MINIMUM is 4,000 m (vs HIGH targets only — the loft geometry and
#   active seeker wasted/blind below the horizon of the seeker dome at 30 km
#   apogee; real-world confirmed engagement floor ~5 km stated in open
#   references).
#
#   Motor sizing to reach 380 km:
#     S300 reference: thrust 200,000 N, burn 12 s, mass 1900 kg ->
#       burnout ~Mach 5.2, coast ~150 km (lofted).
#     To reach 380 km we need substantially more initial energy:
#       Scale motor: thrust 280,000 N, burn 18 s (heavier, longer burn),
#       isp 240 s (same propellant class), mdot = 280,000/(240*9.81) = 119 kg/s
#       => 18 s burns ~2142 kg propellant.  Leaving ~1858 kg body/warhead/seeker
#       from a 4000 kg launch mass.  delta-v ~ thrust*burn/avg_mass
#       = 280000*18 / 3000 ~ 1680 m/s extra, on top of catapult 18 m/s.
#       Burnout speed at loft altitude ~20 km: ~Mach 5-5.5.  Coast from
#       ~20 km apogee at 380 km in ~270-300 s total flight (vs 180 s for
#       S300 at 150 km): the 40N6's practical design apogee ~30 km (published
#       in open references; the higher loft is what extends range in thin air).
#     Loft parameters: the loft is PER ROUND (loft_gain / loft_bias_max /
#       loft_fade_range below) — the 40N6 overrides the medium-loft default
#       with a higher bias and a fade range pushed outside its terminal gate,
#       driving the visible high apogee.  The missile uses the SAME SamMissile
#       phase machine; eject/boost/midcourse/terminal phases work identically.
#       The
#       active seeker (no illuminator) is modelled by passing illuminator_pos_fn=None
#       to SamMissile (the code already handles this: without an illuminator the
#       terminal LOS check runs from the missile's own seeker — exactly the ARH
#       mode).  The world launch_sam('40n6') sets illuminator_pos_fn=None.
#
#   Self-destruct time: 300 s (generous coast to 380 km at average ~1300 m/s;
#     a 380 km shot at Mach 3.5 cruise takes ~340 s — using 360 s so an
#     honest 380 km shot doesn't time out; add margin to 380 s).
#
#   Terminal range for active seeker handover: 40 km (the ARH seeker can see
#   the target from further out in the thin upper-layer air; vs the 48N6's
#   20 km SARH terminal gate).
N40N6 = SamDef(
    weapon_id="40n6", display_name="S-300VM 40N6",
    length=8.0, diameter=0.515, launch_mass=4_000.0, propellant_mass=2_142.0,
    # Same catapult cold-launch sequence as the 48N6 (same TEL family, same
    # delay unit: 1.5 s hang before ignition).
    eject_speed=18.0, eject_time=1.5,
    # Larger motor for 380 km reach (see derivation above).
    motor_thrust=280_000.0, motor_time=18.0, isp=240.0,
    ref_area=0.208,    # same diameter as 48N6: pi * (0.515/2)^2
    max_g=20.0,        # slightly lower agility than 48N6 (heavier airframe)
    fuse_radius=25.0,
    # Active seeker: 40 km terminal gate (ARH self-guides from further out
    # in the thin upper atmosphere where SARH illumination would fade).
    terminal_range=40_000.0,
    max_range=380_000.0,
    self_destruct_t=380.0, self_destruct_speed=250.0,
    # Engagement floor 4,000 m: active seeker + high-loft geometry is
    # effectively blind/wasted below this altitude — the seeker dome looks
    # mostly DOWN in the loft and cannot resolve low-altitude clutter at
    # the intercept geometry (vs HIGH targets only, per spec §4.3b).
    # Real-world open-source references confirm a floor ~5 km; using 4 km
    # as a slightly optimistic game value.
    min_intercept_alt=4_000.0, max_intercept_alt=40_000.0,
    # HIGH lofted trajectory (the discriminator vs the 48N6's medium arc):
    # ``loft_bias_max`` 24 km lofts the midcourse arc to a ~37 km apogee on a
    # long high shot vs the 48N6's ~32 km — the player SEES it climb clearly
    # higher.  ``loft_fade_range`` 45 km sits 5 km OUTSIDE the 40 km terminal
    # gate (mirroring the 48N6's 25 km fade / 20 km terminal), so the loft has
    # faded and the dive is established in midcourse BEFORE the ARH seeker
    # takes over — fixes the BUGHUNT 'overshoots/wallows on close targets'
    # note (a 40 km handover at apogee would wallow).  A short shot stays flat
    # (bias ~0 inside the fade ramp), so it does not over-loft a nearby
    # target: the high loft is the LONG-range energy-management arc, as in
    # reality.  Measured (tools/compare_s300_rounds.py): 37 km apogee, dive
    # handover ~15 km below apogee, kills close movers and reaches past the
    # 48N6's self-destruct range.  Locked by tests/test_s300_rounds_distinct.py.
    loft_gain=0.55, loft_bias_max=24_000.0, loft_fade_range=45_000.0,
)

# 40N6 TEL: same 5P85 body, 2 rounds (the heavier missile halves the load).
# N40N6_AMMO = 2 is the stock constant the world uses.
N40N6_AMMO: int = 2
N40N6_TEL = LauncherDef("40n6_tel", "5P85 TEL (40N6)", ("40n6",), 12.0,
                        tubes=2, ammo=N40N6_AMMO)

# --- 57E6 short-range SAM for Pantsir-S1 (player point defense, Phase 6) ------
# Real 57E6 (9M335 / Vikhr): length 3.17 m, diameter 0.076 m, mass 74 kg
# (warhead + motor). Game represents the full round with a 90 kg total mass
# which includes the container canister adapter dropped at launch.
#
# Motor sizing (derived from SM2 reference; SM2 burns to Mach 5 from rest):
#   Target speed: Mach 2.7 class (~900 m/s at sea level).
#   Mass: 90 kg launch, ~30 kg propellant (same propellant fraction as SM2).
#   Working backward from a ~20 km range shot needing ~25 s total flight:
#     motor_thrust = 18 000 N (solid booster — smaller but same Isp class as SM2)
#     motor_time   = 3.5 s (short fast boost; 57E6 is a sprint interceptor)
#     mdot = 18 000 / (240 * 9.81) = 7.65 kg/s; 3.5 s burns ~26.8 kg ≈ 27 kg.
#     Burnout speed at sea level: Δv ~ F*t / avg_mass = 18000*3.5/76.5 ~824 m/s
#     → Mach ~2.4 at burnout, then coasts; drag-limited to Mach 2.7 peak after
#     momentum builds through the early loft. Consistent with spec §4.2 "Mach
#     2.7 class".
#   Eject: Pantsir mounts the rounds on an elevated turret arm; no cold-launch
#     tube. The round is rail-ejected at ~15 m/s and the motor lights almost
#     immediately (0.3 s — a brief rail-clear delay, far shorter than S-300's
#     1.5 s ballistic hang). Values set at 15 m/s / 0.3 s accordingly.
#   ref_area: pi*(0.076/2)^2 = 0.00454 m^2.
#   max_g: 40 g — the 57E6 is a point-defense sprint missile designed to
#     kill maneuvering cruise missiles and ballistic pop-ups; the real 9M335
#     is quoted at ≥35 g agility (open unclassified references).
#   fuse_radius: 8 m — smaller than SM2/S300 because the Pantsir targets
#     sub-sonic/transonic cruise missiles at close range where the engagement
#     geometry is tight (a large fuse radius at 500 m would trigger on
#     terrain; 8 m is consistent with Russian point-defense SAMs of this class).
#   min_intercept_alt: 5 m — reaches sea-skimmers and pop-up HARMs; the
#     real system is cleared for near-surface engagements (spec §4.2).
#   max_intercept_alt: 15 000 m (15 km) — the published engagement ceiling for
#     the Pantsir-S1 in open references is 15 km; consistent with spec §4.2.
#   terminal_range: 5 000 m — at this proximity the seeker tracks precisely; the
#     smaller terminal handover (vs 20 km for SM2) reflects the shorter sprint.
#   max_range: 20 000 m — spec §4.2 explicit.
#   self_destruct_t: 60 s — 20 km at ~900 m/s average coast is ~22 s; 60 s
#     provides adequate margin and prevents perpetual drifters.
#   self_destruct_speed: 100 m/s — low floor because 57E6 starts subsonic on
#     the rail; the missile must reach Mach 2.7 during boost, so a post-
#     burnout floor of 100 m/s is conservative (it will still be supersonic).
PANTSIR_57E6 = SamDef(
    weapon_id="pantsir_57e6", display_name="57E6 (Pantsir-S1)",
    length=3.17, diameter=0.076,
    launch_mass=90.0,           # kg total (see derivation above)
    propellant_mass=27.0,       # kg solid propellant (see derivation above)
    # Rail-eject: motor lights almost immediately after rail-clear.
    eject_speed=15.0,           # m/s rail-eject speed
    eject_time=0.3,             # s rail-clear delay before ignition
    motor_thrust=18_000.0,      # N solid booster (see derivation above)
    motor_time=3.5,             # s burn (see derivation above)
    isp=240.0,                  # s (same propellant class as S300/SM2)
    ref_area=0.004_536,         # m^2 = pi*(0.076/2)^2
    max_g=40.0,                 # g — sprint intercept vs maneuvering targets
    fuse_radius=8.0,            # m — tight point-defense fuse (see above)
    terminal_range=5_000.0,     # m — seeker handover range
    max_range=20_000.0,         # m — spec §4.2
    self_destruct_t=60.0,       # s (see above)
    self_destruct_speed=100.0,  # m/s post-burnout minimum (see above)
    min_intercept_alt=5.0,      # m — reaches sea-skimmers (spec §4.2)
    max_intercept_alt=15_000.0, # m — published engagement ceiling (spec §4.2)
)

# SM-6 (RIM-174) - enemy ship long-range area-air + anti-surface SAM. Reuses the
# SamMissile machine; 240 km reach lets the fleet engage the recon drone / high
# Oniks at distance and counters the Zircon's high profile.
SM6 = SamDef(
    weapon_id="sm6", display_name="SM-6 (RIM-174)",
    length=6.55, diameter=0.343, launch_mass=1500.0, propellant_mass=1000.0,
    eject_speed=20.0, eject_time=0.5,
    motor_thrust=150_000.0, motor_time=16.0, isp=240.0,
    ref_area=0.0924,   # pi * (0.343/2)^2
    max_g=30.0, fuse_radius=20.0,
    terminal_range=30_000.0, max_range=240_000.0,
    self_destruct_t=300.0, self_destruct_speed=250.0,
    min_intercept_alt=15.0, max_intercept_alt=33_000.0,
)


# --- Bastion-K quasi-ballistic top-attack ASBM (player anti-ship, M4-A) --------
# A LOFTED anti-ship ballistic missile that beats the SM-2 area screen by
# ALTITUDE + SPEED, then dives near-vertically onto a ship deck (DF-21D /
# 3M22-class concept).  It REUSES the SamMissile loft+boost+coast+PN+fuse
# machine UNCHANGED; only the terminal seeker is overridden (sim/asbm.py
# AsbmMissile) to lock the nearest SHIP in a cone instead of an air target.
#
#   Anti-ship, not anti-air, so the SamDef differs from the 40N6 in three ways
#   that MATTER:
#     1. min_intercept_alt = 0 (dives to the SEA — a ship deck at ~12 m), NOT
#        the 40N6's 4 km active-seeker floor (that round is blind low; this one
#        is BUILT to hit the surface).
#     2. A MUCH higher loft (loft_bias_max 90 km, loft_gain 2.0, a short
#        loft_fade_range 15 km) drives a near-vertical climb to a ~90 km exo
#        apogee held until close to the target — the quasi-ballistic arc.
#     3. terminal_range 20 km: the MaRV hands over PARTWAY DOWN the steep
#        ballistic reentry, NOT at apogee, so the handover flight-path angle is
#        already steeper than -60 deg.  (Handing over at apogee would wallow —
#        the same lesson as the 40N6's fade-outside-the-gate trick.)
#
#   MEASURED flight profile (tools/probe_asbm_flyoff.py, static ship, seed-free
#   truth flyoff; the env test locks to THIS band, two-sided):
#       range  apogee   handover-FPA  terminal-min-FPA  peakMach  reentryMach  result
#       100km  67.7 km     -61.2 deg      -90.0 deg       4.34       3.95       HIT
#       200km  90.0 km     -71.0 deg      -84.9 deg       4.34       3.98       HIT
#       250km  90.0 km     -70.6 deg      -85.1 deg       4.34       3.98       HIT  <- probe range
#       300km  90.0 km     -70.6 deg      -85.1 deg       4.34       3.98       HIT
#       350km   -- (energy self-destruct, clean range gate) --                  MISS
#     Apogee >= 40 km, dive steeper than -60 deg at handover and ~vertical by
#     impact, midcourse cruise altitude ~8 km (stays ABOVE the SM6_AREA_MIN_ALT_M
#     1500 m band so the high midcourse is SM-6-targetable — the existing
#     counter still bites).  Peak boost Mach 4.34, reentry Mach ~4.0.
#
#   The loft/descent gains are shared with the SamMissile and are Mach-2.5-tuned
#   (project memory); the ASBM does NOT fight them — the steep dive comes from
#   the BALLISTIC fall off a 90 km apogee that the shallow midcourse steering
#   physically cannot arrest, plus the no-cap terminal PN.  MEASURED, not copied.
BASTION_K = SamDef(
    weapon_id="asbm", display_name="Bastion-K ASBM",
    length=8.0, diameter=0.62, launch_mass=4_200.0, propellant_mass=2_000.0,
    # Cold catapult eject + short hang, then a long high-thrust solid boost.
    eject_speed=18.0, eject_time=1.0,
    motor_thrust=300_000.0, motor_time=16.0, isp=245.0,   # = propellant/mdot
    ref_area=0.302,    # pi * (0.62/2)^2
    max_g=22.0, fuse_radius=20.0,
    # Terminal handover partway down the reentry (see note above).
    terminal_range=20_000.0, max_range=300_000.0,
    self_destruct_t=400.0, self_destruct_speed=200.0,
    # Dives to the SEA: floor 0 (a ship deck), ceiling well above the apogee.
    min_intercept_alt=0.0, max_intercept_alt=95_000.0,
    # The quasi-ballistic loft: near-vertical climb to a ~90 km exo apogee held
    # until close to the target (short fade), so the reentry over the hull is
    # steep.  These three are the ASBM's discriminator vs every other SamDef.
    loft_gain=2.0, loft_bias_max=90_000.0, loft_fade_range=15_000.0,
)

# Bastion-K ASBM ammo pool default (scarce, like the Zircon).  The world reads
# config.asbm_ammo (default 0 -> the round is never offered: byte-identical
# default battle).  This constant is the in-arsenal nominal stock.
BASTION_K_AMMO: int = 4


WEAPONS = {"oniks": ONIKS, "zircon": ZIRCON}
SAMS = {"s300": S300, "sm2": SM2, "40n6": N40N6, "pantsir_57e6": PANTSIR_57E6,
        "sm6": SM6, "asbm": BASTION_K}
STRIKES = {"tomahawk": TOMAHAWK, "jassm": JASSM, "harm": HARM, "kh31p": KH31P}
LAUNCHERS = {"bastion": BASTION, "s300_tel": S300_TEL, "sm2_vls": SM2_VLS,
             "40n6_tel": N40N6_TEL}
