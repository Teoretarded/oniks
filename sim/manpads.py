"""Man-portable SAM physics for the cinematic walk mode.

GL-free (unit tests drive everything headless). Four researched systems —
Igla-S, Stinger, Piorun, Starstreak — with launch sequences, thrust
phases, Mach-dependent drag and TRUE proportional navigation whose
lateral authority is exactly what the airframe gives: normal force from
dynamic pressure and trim angle-of-attack, hard-capped by the structural
load limit (gravity trim included in the budget). Hit or miss EMERGES
from these limits — there is no probability roll anywhere and no RNG at
all in this module.

Specs and sources: docs/research/manpads_reference.md. Values marked ~
there are estimates; each is one field below.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

GRAVITY = 9.81
RHO0 = 1.225                 # kg/m^3 sea level
SCALE_H = 8500.0             # m, exponential atmosphere
SPEED_OF_SOUND = 320.0       # m/s (cool alpine air, matches sim/missile.py)

# Terminal phase: inside this range the last guidance command is held —
# real seekers saturate at end-game LOS rates but the geometry is set.
TERMINAL_RANGE_M = 120.0
OCCLUSION_DT = 0.04          # s between terrain line-of-sight checks
OCCLUSION_STEP_M = 40.0      # m between DTM samples along the sight line


def air_density(alt_m: float) -> float:
    return RHO0 * math.exp(-max(alt_m, 0.0) / SCALE_H)


def drag_coefficient(mach: float) -> float:
    """Slender finned-body Cd(M): flat subsonic, transonic hump at ~M1.05
    decaying to a supersonic floor (same curve family as sim/aero.py)."""
    m = max(mach, 0.0)
    if m < 0.8:
        return 0.30
    if m < 1.05:
        return 0.30 + (0.75 - 0.30) * (m - 0.8) / 0.25
    return 0.34 + 0.41 * math.exp(-(m - 1.05) / 0.623)


@dataclass(frozen=True)
class ManpadsSpec:
    id: str
    label: str
    nation: str
    blurb: str                  # one-line locker UI description
    length_m: float
    diameter_m: float
    mass_kg: float
    warhead_kg: float
    eject_v: float              # m/s tube-exit velocity (eject charge)
    ignite_dist_m: float        # flight motor lights this far out
    boost_s: float
    boost_thrust_n: float
    sustain_s: float
    sustain_thrust_n: float
    peak_speed_ms: float        # published figure (UI + sanity)
    range_m: float
    min_range_m: float          # published minimum engagement range
    ceiling_m: float
    life_s: float               # self-destruct timer
    seeker: str                 # 'ir' | 'beam'
    acq_cone_deg: float         # seeker instantaneous FOV half-angle
    gimbal_deg: float           # max seeker angle off the missile axis
    track_rate_dps: float       # seeker slew limit
    nav_gain: float             # PN navigation constant N
    g_limit: float              # structural load factor limit
    aoa_max_deg: float          # max trim angle of attack (fin authority)
    cn_alpha: float             # normal-force slope per rad
    prox_radius_m: float        # 0 = impact fuse only
    lock_range_m: float         # IR acquisition vs a burning motor
    lock_range_ground_m: float  # IR vs hot ground clutter (0 = never)
    reload_s: float             # new tube on the shoulder
    ads_fov_deg: float          # sight zoom FOV
    # Fire control adds pitch above the sight line at launch (FM 44-18-1:
    # Stinger inserts super-elevation automatically) — without it a flat
    # shot sags into the ground before the fins have dynamic pressure.
    super_elev_deg: float = 10.0
    # Igla-family gas-piston assist (documented perpendicular gas tubes
    # that steer the round before the fins have dynamic pressure).
    assist_ms2: float = 0.0
    assist_s: float = 0.0
    # Starstreak: darts separate at burnout and coast.
    dart_sep: bool = False
    dart_mass_kg: float = 0.0   # guided triplet total
    dart_area_m2: float = 0.0   # summed frontal area of the darts
    dart_cd_scale: float = 1.0  # needle-body drag vs the stack curve
    dart_g_limit: float = 0.0
    dart_spread_m: float = 0.0  # formation envelope around the beam axis
    # Trail cosmetics (rig-side rendering only, never guidance).
    smoke_per_m: float = 0.5
    trail_width_m: float = 0.5
    corkscrew_m: float = 0.0    # rolling-airframe helix amplitude
    flame_len_m: float = 1.2


WEAPONS = (
    ManpadsSpec(
        id="igla_s", label="9K338 IGLA-S", nation="RU",
        blurb="SA-24 GRINCH - 2-BAND IR, LASER PROX FUSE",
        length_m=1.635, diameter_m=0.072, mass_kg=11.7, warhead_kg=2.5,
        eject_v=28.0, ignite_dist_m=5.5,
        boost_s=2.0, boost_thrust_n=3700.0,
        sustain_s=5.5, sustain_thrust_n=520.0,
        peak_speed_ms=600.0, range_m=6000.0, min_range_m=500.0,
        ceiling_m=3500.0, life_s=15.0,
        seeker="ir", acq_cone_deg=4.0, gimbal_deg=40.0, track_rate_dps=12.0,
        nav_gain=3.7, g_limit=16.0, aoa_max_deg=18.0, cn_alpha=12.0,
        prox_radius_m=1.5, lock_range_m=6000.0, lock_range_ground_m=1500.0,
        reload_s=4.5, ads_fov_deg=32.0,
        assist_ms2=18.0, assist_s=0.5,
        smoke_per_m=0.55, trail_width_m=0.42, corkscrew_m=0.5,
        flame_len_m=1.3),
    ManpadsSpec(
        id="stinger", label="FIM-92 STINGER", nation="US",
        blurb="IR/UV ROSETTE SCAN - MACH 2.2 IN TWO SECONDS",
        length_m=1.52, diameter_m=0.070, mass_kg=10.1, warhead_kg=3.0,
        eject_v=28.0, ignite_dist_m=9.0,
        boost_s=1.9, boost_thrust_n=4300.0,
        sustain_s=6.0, sustain_thrust_n=420.0,
        peak_speed_ms=750.0, range_m=4800.0, min_range_m=200.0,
        ceiling_m=3800.0, life_s=17.0,
        seeker="ir", acq_cone_deg=4.5, gimbal_deg=40.0, track_rate_dps=20.0,
        nav_gain=3.8, g_limit=20.0, aoa_max_deg=20.0, cn_alpha=12.0,
        prox_radius_m=2.0, lock_range_m=5200.0, lock_range_ground_m=1200.0,
        reload_s=4.0, ads_fov_deg=34.0,
        smoke_per_m=0.50, trail_width_m=0.40, corkscrew_m=0.35,
        flame_len_m=1.2),
    ManpadsSpec(
        id="piorun", label="PIORUN", nation="PL",
        blurb="THUNDER - MODERN SEEKER, PROX FUSE, 6.5 KM",
        length_m=1.596, diameter_m=0.072, mass_kg=10.5, warhead_kg=1.82,
        eject_v=28.0, ignite_dist_m=5.5,
        boost_s=2.0, boost_thrust_n=3550.0,
        sustain_s=5.5, sustain_thrust_n=460.0,
        peak_speed_ms=660.0, range_m=6500.0, min_range_m=400.0,
        ceiling_m=4000.0, life_s=14.0,
        seeker="ir", acq_cone_deg=4.0, gimbal_deg=40.0, track_rate_dps=15.0,
        nav_gain=3.7, g_limit=18.0, aoa_max_deg=18.0, cn_alpha=12.0,
        prox_radius_m=1.5, lock_range_m=6500.0, lock_range_ground_m=1600.0,
        reload_s=4.5, ads_fov_deg=30.0,
        assist_ms2=18.0, assist_s=0.5,
        smoke_per_m=0.50, trail_width_m=0.40, corkscrew_m=0.45,
        flame_len_m=1.25),
    ManpadsSpec(
        id="starstreak", label="STARSTREAK HVM", nation="UK",
        blurb="LASER BEAM RIDER - MACH 3.5, THREE TUNGSTEN DARTS",
        length_m=1.40, diameter_m=0.130, mass_kg=14.0, warhead_kg=2.7,
        eject_v=55.0, ignite_dist_m=4.0,
        # Mach 3.5 within ~350 m of the muzzle (the fastest SHORAD in
        # service): a ~0.6 s second-stage burn near 190 g axial, then
        # the darts separate and coast.
        boost_s=0.6, boost_thrust_n=27600.0,
        sustain_s=0.0, sustain_thrust_n=0.0,
        peak_speed_ms=1190.0, range_m=7000.0, min_range_m=300.0,
        ceiling_m=5000.0, life_s=12.0,
        seeker="beam", acq_cone_deg=0.0, gimbal_deg=0.0, track_rate_dps=0.0,
        nav_gain=4.0, g_limit=20.0, aoa_max_deg=10.0, cn_alpha=10.0,
        prox_radius_m=0.0, lock_range_m=7000.0, lock_range_ground_m=7000.0,
        reload_s=6.0, ads_fov_deg=26.0,
        super_elev_deg=1.5,      # beam riders launch nearly ON the line;
                                 # a whisker of gathering elevation keeps
                                 # the q-starved first 200 m off the turf
        dart_sep=True, dart_mass_kg=2.7,
        dart_area_m2=3.0 * math.pi * 0.011 ** 2, dart_cd_scale=0.42,
        dart_g_limit=20.0, dart_spread_m=1.5,
        smoke_per_m=0.30, trail_width_m=0.55, corkscrew_m=0.0,
        flame_len_m=2.2),
)

WEAPON_BY_ID = {w.id: w for w in WEAPONS}


def _unit(v: np.ndarray) -> np.ndarray:
    n = float(np.linalg.norm(v))
    return v / n if n > 1e-12 else np.array([0.0, 0.0, 1.0])


def _rotate_toward(axis: np.ndarray, want: np.ndarray,
                   max_rad: float) -> np.ndarray:
    """Rotate unit vector ``axis`` toward unit vector ``want`` by at most
    ``max_rad`` (the seeker slew limit)."""
    c = float(np.clip(np.dot(axis, want), -1.0, 1.0))
    ang = math.acos(c)
    if ang <= max_rad or ang < 1e-9:
        return want.copy()
    # Slerp by max_rad/ang along the great circle.
    perp = _unit(want - axis * c)
    return _unit(axis * math.cos(max_rad) + perp * math.sin(max_rad))


class ManpadsRound:
    """One shoulder-fired round in flight.

    ``target`` duck-types ScriptedLaunch (.pos, .vel ndarray, .done, and
    optionally .burning()); ``ground_point`` is a fixed designated point;
    ``ground_h(x, z)`` samples terrain for impact + IR occlusion. Events
    appended by step(): ('ignite'|'burnout'|'dart_sep'|'lock_lost'|
    'hit'|'ground'|'self_destruct', pos ndarray).
    """

    def __init__(self, spec: ManpadsSpec, pos, direction, target=None,
                 ground_point=None, ground_h=None, victims=None):
        self.spec = spec
        self.pos = np.asarray(pos, dtype=np.float64).copy()
        d = _unit(np.asarray(direction, dtype=np.float64))
        if spec.super_elev_deg > 0.0:
            yaw = math.atan2(float(d[0]), float(d[2]))
            pitch = math.asin(float(np.clip(d[1], -1.0, 1.0)))
            pitch = min(pitch + math.radians(spec.super_elev_deg),
                        math.radians(88.0))
            cp = math.cos(pitch)
            d = np.array([math.sin(yaw) * cp, math.sin(pitch),
                          math.cos(yaw) * cp])
        self.vel = d * spec.eject_v
        self.t = 0.0
        self.phase = "eject"
        self.done = False
        self.hit = False
        self.miss_dist = None          # closest recorded approach (m)
        self.target = target
        self.ground_point = None if ground_point is None \
            else np.asarray(ground_point, dtype=np.float64).copy()
        self.ground_h = ground_h
        self.lock = target is not None or ground_point is not None
        self.darts = False             # Starstreak: past separation
        self._launch_pos = self.pos.copy()
        self._ignite_t = None          # set when the flight motor lights
        self._seeker = None            # unit vector, set on first track
        if target is not None:
            self._seeker = _unit(np.asarray(target.pos, dtype=np.float64)
                                 - self.pos)
        self._a_lat = np.zeros(3)      # held through the terminal phase
        self._occ_left = 0.0
        self._rel_prev = None          # relative position after last step
        self._tvel_prev = None         # beam: point velocity, last step
        self._at_lp = None             # beam: filtered line acceleration
        # The warhead does not care what it was AIMED at: everything the
        # caller lists here is fuse-checked with the same segment test (a
        # beam round threading a flying S-300 must frag it).
        self.victims = victims         # callable -> iterable of objects
        self.victim = None             # what the fuse actually caught
        self._vrel_prev = {}           # id(victim) -> rel after last step

    # ---------------------------------------------------------- properties

    @property
    def burning(self) -> bool:
        if self._ignite_t is None:
            return False
        tb = self.t - self._ignite_t
        return tb < self.spec.boost_s + self.spec.sustain_s

    @property
    def boosting(self) -> bool:
        return (self._ignite_t is not None
                and self.t - self._ignite_t < self.spec.boost_s)

    def heading(self) -> np.ndarray:
        return _unit(self.vel)

    # ---------------------------------------------------------------- step

    def step(self, dt: float, events: list) -> None:
        if self.done:
            return
        s = self.spec
        dt = float(dt)
        if not math.isfinite(dt) or dt <= 0.0:
            return
        self._dt_hint = dt
        self.t += dt

        if self.t >= s.life_s:
            self.done = True
            events.append(("self_destruct", self.pos.copy()))
            return

        # -- target bookkeeping. The fuse segment runs from the relative
        #    position recorded after the LAST step to the one after this
        #    step, so target motion between our steps is covered too — a
        #    Mach-2 head-on pass moves >10 m of relative position per
        #    240 Hz step and must not slip between samples.
        tpos, tvel = self._target_state()
        rel0 = self._rel_prev
        if rel0 is None and tpos is not None:
            rel0 = tpos - self.pos

        # -- propulsion phases
        thrust = 0.0
        if self.phase == "eject":
            d = float(np.linalg.norm(self.pos - self._launch_pos))
            if d >= s.ignite_dist_m:
                self.phase = "boost"
                self._ignite_t = self.t
                events.append(("ignite", self.pos.copy()))
        if self._ignite_t is not None:
            tb = self.t - self._ignite_t
            if tb < s.boost_s:
                self.phase = "boost"
                thrust = s.boost_thrust_n
            elif tb < s.boost_s + s.sustain_s:
                self.phase = "sustain"
                thrust = s.sustain_thrust_n
            else:
                if self.phase in ("boost", "sustain"):
                    # burnout = ALL thrust ends (boost->sustain is not it)
                    events.append(("burnout", self.pos.copy()))
                    self._maybe_separate(events)
                self.phase = "coast"

        # -- forces
        v = float(np.linalg.norm(self.vel))
        vdir = self.heading()
        mach = v / SPEED_OF_SOUND
        mass = s.dart_mass_kg if self.darts else s.mass_kg
        if self.darts:
            area = s.dart_area_m2
            cd = drag_coefficient(mach) * s.dart_cd_scale
        else:
            area = math.pi * (s.diameter_m * 0.5) ** 2
            cd = drag_coefficient(mach)
        q = 0.5 * air_density(float(self.pos[1])) * v * v
        acc = np.array([0.0, -GRAVITY, 0.0])
        acc = acc + vdir * (thrust / mass - q * cd * area / mass)

        # -- guidance (fins need dynamic pressure; eject phase is inert)
        if self.phase != "eject" and (tpos is not None):
            self._a_lat = self._guidance(tpos, tvel, vdir, q, area, mass,
                                         events)
        elif self.phase == "eject":
            self._a_lat = np.zeros(3)
        acc = acc + self._a_lat

        # -- integrate (semi-implicit Euler, deterministic)
        self.vel = self.vel + acc * dt
        self.pos = self.pos + self.vel * dt

        # -- fuse: closest approach on this step's RELATIVE segment
        if rel0 is not None:
            tpos1, _ = self._target_state()
            if tpos1 is not None:
                rel1 = tpos1 - self.pos
                self._rel_prev = rel1
                miss = _body_miss(self.target, rel0, rel1)
                if self.miss_dist is None or miss < self.miss_dist:
                    self.miss_dist = miss
                kill = s.prox_radius_m + s.diameter_m \
                    + self._target_radius()
                if self.darts:
                    # any of the three darts hitting counts: the triplet
                    # flies a ~1.5 m formation around the beam axis
                    kill += s.dart_spread_m
                if miss <= kill:
                    self.done = True
                    self.hit = True
                    if self.target is not None:
                        self.victim = self.target
                    events.append(("hit", self.pos.copy()))
                    return

        # -- anything else passing inside the fuse envelope
        if self.victims is not None and self._check_victims(events):
            return

        # -- terrain impact
        if self.ground_h is not None:
            if self.ground_h(float(self.pos[0]), float(self.pos[2])) \
                    >= float(self.pos[1]):
                self.done = True
                # Near the designated point this IS the delivery.
                if self.ground_point is not None and float(np.linalg.norm(
                        self.pos - self.ground_point)) <= 12.0:
                    self.hit = True
                events.append(("ground", self.pos.copy()))
                return

    # ------------------------------------------------------------ internals

    def _check_victims(self, events: list) -> bool:
        s = self.spec
        for v in self.victims():
            if v is self.target or getattr(v, "done", False):
                continue
            rel1 = np.asarray(v.pos, dtype=np.float64) - self.pos
            rel0 = self._vrel_prev.get(id(v))
            self._vrel_prev[id(v)] = rel1
            if rel0 is None:
                continue
            radius = getattr(v, "radius", None)
            if radius is None:
                radius = _body_radius(v)
            kill = s.prox_radius_m + s.diameter_m + float(radius)
            if self.darts:
                kill += s.dart_spread_m
            if _body_miss(v, rel0, rel1) <= kill:
                self.done = True
                self.hit = True
                self.victim = v
                events.append(("hit", self.pos.copy()))
                return True
        return False

    def _maybe_separate(self, events: list) -> None:
        if self.spec.dart_sep and not self.darts:
            self.darts = True
            events.append(("dart_sep", self.pos.copy()))

    def _target_state(self):
        if self.target is not None and not getattr(self.target, "done",
                                                   False):
            return (np.asarray(self.target.pos, dtype=np.float64),
                    np.asarray(getattr(self.target, "vel",
                                       np.zeros(3)), dtype=np.float64))
        if self.ground_point is not None:
            return self.ground_point, np.zeros(3)
        return None, None

    def _target_radius(self) -> float:
        """Effective target radius around the fuse geometry: an explicit
        .radius wins; airframes with a known axis are handled as capsules
        by _body_miss and only need their body radius here."""
        if self.target is None:
            return 0.0
        r = getattr(self.target, "radius", None)
        if r is not None:
            return float(r)
        return _body_radius(self.target)

    def _guidance(self, tpos, tvel, vdir, q, area, mass,
                  events) -> np.ndarray:
        s = self.spec
        rel = tpos - self.pos
        rng = float(np.linalg.norm(rel))
        if rng < 1e-6:
            return np.zeros(3)
        los = rel / rng

        if not self.lock:
            return np.zeros(3)

        # Seeker head limits (IR only; the beam is held by the operator).
        if s.seeker == "ir" and rng > TERMINAL_RANGE_M:
            if self._seeker is None:
                self._seeker = los.copy()
            # Track: slew the head toward the LOS at the rate limit.
            self._seeker = _rotate_toward(self._seeker, los,
                                          math.radians(s.track_rate_dps)
                                          * self._dt_hint)
            off = math.degrees(math.acos(float(np.clip(
                np.dot(self._seeker, los), -1.0, 1.0))))
            gim = math.degrees(math.acos(float(np.clip(
                np.dot(self._seeker, vdir), -1.0, 1.0))))
            if off > s.acq_cone_deg or gim > s.gimbal_deg:
                self.lock = False
                events.append(("lock_lost", self.pos.copy()))
                return np.zeros(3)
            if self._occluded(tpos):
                self.lock = False
                events.append(("lock_lost", self.pos.copy()))
                return np.zeros(3)

        # True proportional navigation + gravity trim: the autopilot holds
        # trim AoA against gravity sag (without it a flat valley shot
        # noses into the ground within 30 m, and a beam rider grazes
        # below the sight line). The structural budget below reserves
        # exactly this 1 g.
        vrel = tvel - self.vel
        omega = np.cross(rel, vrel) / (rng * rng)
        vc = -float(np.dot(rel, vrel)) / rng
        a_cmd = s.nav_gain * max(vc, 50.0) * np.cross(omega, los)
        if s.seeker == "beam":
            # CLOS: the dart follows the LINE including its acceleration
            # (classic APN feedforward). An IR seeker can't observe target
            # acceleration — only the beam computer on the ground can.
            # The raw double-derivative of a HAND-steered point is mostly
            # aim quantization noise (the sight updates slower than the
            # sim), so it is low-passed (~50 ms tracker filter) and
            # bounded at the real target-acceleration scale — unfiltered
            # it saturates the fins alternately up/down and the round
            # flies ballistic.
            if self._tvel_prev is not None and self._dt_hint > 1e-6:
                raw = (tvel - self._tvel_prev) / self._dt_hint
                if self._at_lp is None:
                    self._at_lp = np.zeros(3)
                self._at_lp = self._at_lp * 0.92 + raw * 0.08
                a_t = self._at_lp
                n_at = float(np.linalg.norm(a_t))
                if n_at > 160.0:
                    a_t = a_t * (160.0 / n_at)
                a_cmd = a_cmd + 0.5 * s.nav_gain \
                    * (a_t - los * float(np.dot(a_t, los)))
            self._tvel_prev = tvel.copy()
        g_vec = np.array([0.0, -GRAVITY, 0.0])
        a_cmd = a_cmd - (g_vec - vdir * float(np.dot(g_vec, vdir)))
        # Fins produce normal force: project the command off the axis.
        a_cmd = a_cmd - vdir * float(np.dot(a_cmd, vdir))

        # Fin authority: what the airframe can ACTUALLY give right now.
        g_lim = (s.dart_g_limit if self.darts else s.g_limit)
        a_struct = max(g_lim * GRAVITY - GRAVITY, 0.0)
        a_aero = q * area * s.cn_alpha * math.radians(s.aoa_max_deg) / mass
        a_max = min(a_struct, a_aero)
        if self._ignite_t is not None and \
                self.t - self._ignite_t < s.assist_s:
            a_max += s.assist_ms2
        n = float(np.linalg.norm(a_cmd))
        if n > a_max:
            a_cmd = a_cmd * (a_max / max(n, 1e-9))
        return a_cmd

    def _occluded(self, tpos) -> bool:
        """Coarse DTM march along the sight line every OCCLUSION_DT."""
        if self.ground_h is None:
            return False
        self._occ_left -= self._dt_hint
        if self._occ_left > 0.0:
            return False
        self._occ_left = OCCLUSION_DT
        rel = tpos - self.pos
        dist = float(np.linalg.norm(rel))
        n = max(int(dist / OCCLUSION_STEP_M), 1)
        d = rel / n
        p = self.pos.copy()
        for _ in range(n - 1):
            p = p + d
            if self.ground_h(float(p[0]), float(p[2])) >= float(p[1]):
                return True
        return False

    # step() stores the current dt for the seeker/occlusion helpers.
    _dt_hint = 1.0 / 240.0


def _segment_min_dist(r0: np.ndarray, r1: np.ndarray) -> float:
    """Minimum |r| along the straight segment r0 -> r1 (the relative
    position across one integration step): the between-step fuse."""
    d = r1 - r0
    dd = float(np.dot(d, d))
    if dd < 1e-12:
        return float(np.linalg.norm(r0))
    u = -float(np.dot(r0, d)) / dd
    u = min(max(u, 0.0), 1.0)
    return float(np.linalg.norm(r0 + d * u))


def _body_radius(obj) -> float:
    """Fuse radius of a target's BODY (not its length — the length is
    the capsule in _body_miss): ~7% of length matches the slender
    airframes here (48N6: 7.5 m long, 0.52 m across)."""
    length = getattr(getattr(obj, "variant", None), "length_m", None)
    return max(float(length) * 0.07, 0.2) if length else 0.5


def _body_miss(obj, rel0: np.ndarray, rel1: np.ndarray) -> float:
    """Miss distance from the relative path to the target BODY: a capsule
    along the airframe axis when known, else the center point."""
    length = getattr(getattr(obj, "variant", None), "length_m", None)
    axis = getattr(obj, "axis", None)
    if length is not None and axis is not None:
        a = np.asarray(axis, dtype=np.float64)
        n = float(np.linalg.norm(a))
        if n > 1e-9:
            return _capsule_min_dist(rel0, rel1, a / n,
                                     float(length) * 0.5)
    return _segment_min_dist(rel0, rel1)


def _capsule_min_dist(r0: np.ndarray, r1: np.ndarray, axis: np.ndarray,
                      half_len: float) -> float:
    """Minimum distance between the relative-motion segment r0 -> r1 and
    the target BODY segment (+-axis*half_len about the target center) —
    a 7.5 m airframe is not a point; a 'miss' 4 m off center can be a
    sub-meter pass off the nose. Standard clamped segment-segment
    closest-approach (the body axis is frozen across one step)."""
    d1 = r1 - r0                      # relative path
    d2 = axis * (2.0 * half_len)      # body, from tail end
    p1 = r0
    p2 = -axis * half_len
    r = p1 - p2
    a = float(np.dot(d1, d1))
    e = float(np.dot(d2, d2))
    f = float(np.dot(d2, r))
    if a < 1e-12 and e < 1e-12:
        return float(np.linalg.norm(r))
    if a < 1e-12:
        s, u = 0.0, min(max(f / e, 0.0), 1.0)
    else:
        c = float(np.dot(d1, r))
        if e < 1e-12:
            u, s = 0.0, min(max(-c / a, 0.0), 1.0)
        else:
            b = float(np.dot(d1, d2))
            den = a * e - b * b
            s = min(max((b * f - c * e) / den, 0.0), 1.0) \
                if den > 1e-12 else 0.0
            u = (b * s + f) / e
            if u < 0.0:
                u, s = 0.0, min(max(-c / a, 0.0), 1.0)
            elif u > 1.0:
                u, s = 1.0, min(max((b - c) / a, 0.0), 1.0)
    return float(np.linalg.norm((p1 + d1 * s) - (p2 + d2 * u)))
