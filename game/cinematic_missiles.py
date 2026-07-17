"""Missile variants + scripted cold-launch kinematics for cinematic mode.

GL-free (unit tests drive everything here headless): kinematics are pure
math and the emission half only touches the GL-free particle POOLS of
``engine.particles.Effects``.

Each variant carries its own visual identity — burn time, acceleration,
flame length/color, smoke color/width/persistence — so switching rounds
(K key / the overlay UI) visibly changes the launch.  Values are grounded
in launch-footage phenomenology of the S-300/S-400 family; entries marked
`~` in the research notes are best estimates, kept in one table so a
better number is a one-line edit (docs/cinematic_mode_run_log_2026-07-16).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from engine.particles import (
    Effects,
    FIRE_BUOYANCY,
    FIRE_DRAG,
    SPRAY_GRAVITY,
)

GRAVITY = 9.81


class CinematicEffects(Effects):
    """Effects with column-friendly smoke physics.

    The combat tuning (SMOKE_BUOYANCY 1.7 / drag 0.45) gives every smoke
    particle a PERMANENT 3.8 m/s terminal climb — right for ten-second
    battle puffs, but a five-minute launch column visibly rides an
    elevator (user report, phase 3).  Here the initial hot rise lives in
    the EMIT velocity and decays under drag; the standing buoyancy only
    holds a ~0.2 m/s residual creep, so a 30 s old column hangs, churns
    and thins the way the footage does.

    ``wind_profile`` (world.cinematic_wind.WindProfile, optional) makes
    the ambient flow ALTITUDE-DEPENDENT from a year of measured data:
    the pad cloud drifts on the valley breeze while the high column
    shears off on the ridge-top westerlies.  Without a profile the old
    constant valley WIND applies (tests, unbaked scenes)."""

    def __init__(self, seed: int = 0, wind_profile=None):
        super().__init__(seed=seed)
        self.wind_profile = wind_profile
        self.t = 0.0
        # Dedicated fog pool (world/cinematic_fog.py steers it; the
        # particle renderer draws any effects.fog it finds).
        from engine.particles import ParticlePool
        from world.cinematic_fog import FOG_CAP
        self.fog = ParticlePool(FOG_CAP)

    def wind_at(self, y: float) -> np.ndarray:
        """(3,) ambient wind at scene height y (emission helper)."""
        if self.wind_profile is not None:
            return self.wind_profile.wind_at(y, self.t)
        return WIND.astype(np.float64)

    def update(self, dt) -> None:
        self.t += dt
        if self.wind_profile is not None:
            wp, t = self.wind_profile, self.t
            wind = lambda ys: wp.wind_field(ys, t)   # noqa: E731
        else:
            wind = WIND
        self.smoke.update(dt, drag=0.90, buoyancy=0.045, wind=wind)
        self.fire.update(dt, drag=FIRE_DRAG, buoyancy=FIRE_BUOYANCY)
        self.spray.update(dt, drag=0.15, gravity=SPRAY_GRAVITY)
        for trail in self.trails:
            trail.update(dt)
        self.trails = [t for t in self.trails
                       if not (t.finished and len(t) == 0)]


@dataclass(frozen=True)
class MissileVariant:
    id: str
    label: str
    blurb: str                  # one-line UI description
    length_m: float
    eject_v0: float             # m/s vertical cold-launch eject
    ignite_delay: float         # s of unlit hang before light-off
    boost_accel: float          # m/s^2 along the axis while burning
    burns: tuple                # ((start_s, end_s), ...) after ignition
    tilt_rate_deg: float        # pitch-over rate after ignition
    tilt_max_deg: float
    flame_len_m: float          # visible flame length behind the nozzle
    flame_core: tuple           # additive core color
    flame_edge: tuple
    smoke_fresh: tuple          # column color at emission
    smoke_old: tuple            # color it fades toward
    smoke_rate: float           # legacy field (kept for the tests/UI)
    smoke_size: tuple           # billow (birth, death) size in m
    column_persist_s: float     # veil particle life
    fireball_scale: float       # ignition fireball multiplier
    life_s: float               # despawn
    # Art direction per GPT-5.6 xhigh consult (docs/research doc):
    smoke_per_m: float = 1.8    # total column particles per meter flown
    width_mult: float = 1.0     # column/cloud width multiplier
    base_cloud_mult: float = 1.0    # eject cloud scale
    ground_blast_mult: float = 1.0  # pad wall-jet particle scale
    shake_amp: float = 0.75     # observer shake (m) at the acoustic hit
    # Flight-computer data (universal T-targeting, 2026-07-17): open
    # figures for the real rounds — mass, body diameter, an average
    # supersonic Cd, structural g ceiling, aero lift authority, the
    # published engagement range, and the warhead for impact scale.
    mass_kg: float = 1800.0
    diam_m: float = 0.519
    cd: float = 0.32
    g_max: float = 25.0
    lift_q_gain: float = 4.0e-4   # lat m/s^2 per Pa of dynamic pressure
    range_km: float = 150.0
    warhead_kg: float = 145.0


# Values from docs/research/s300_launch_visuals.md (GPT-5.6 Sol footage
# research 2026-07-16): ignition ~0.75-1.0 s after tube exit at ~25-32 m,
# burns of 8-12+ s at 14-20 g, flame ~0.9-1.4x body length, smoke columns
# that hang for MINUTES.  Accels are the researched averages (m/s^2).
VARIANTS = (
    MissileVariant(
        id="48n6", label="48N6", blurb="THE HEAVY CLASSIC - 12 S OF BURN",
        length_m=7.5, eject_v0=35.0, ignite_delay=0.9,
        boost_accel=160.0, burns=((0.0, 12.0),),
        tilt_rate_deg=7.0, tilt_max_deg=34.0,
        flame_len_m=9.0, flame_core=(1.0, 0.98, 0.88),
        flame_edge=(1.0, 0.57, 0.14),
        smoke_fresh=(0.93, 0.92, 0.86), smoke_old=(0.69, 0.71, 0.71),
        smoke_rate=68.0, smoke_size=(6.5, 50.0), column_persist_s=280.0,
        fireball_scale=1.0, life_s=40.0,
        smoke_per_m=2.00, width_mult=1.0, base_cloud_mult=1.30,
        ground_blast_mult=1.15, shake_amp=0.75,
        mass_kg=1835.0, diam_m=0.519, cd=0.32, g_max=25.0,
        lift_q_gain=4.0e-4, range_km=150.0, warhead_kg=145.0),
    MissileVariant(
        id="5v55", label="5V55", blurb="FIRST GENERATION - FILTHY OLD BOOSTER",
        length_m=7.25, eject_v0=30.0, ignite_delay=0.85,
        boost_accel=175.0, burns=((0.0, 10.0),),
        tilt_rate_deg=6.0, tilt_max_deg=28.0,
        flame_len_m=9.5, flame_core=(1.0, 0.93, 0.78),
        flame_edge=(1.0, 0.47, 0.10),
        smoke_fresh=(0.88, 0.86, 0.78), smoke_old=(0.60, 0.61, 0.60),
        smoke_rate=78.0, smoke_size=(6.0, 46.0), column_persist_s=240.0,
        fireball_scale=0.9, life_s=32.0,
        smoke_per_m=2.60, width_mult=1.15, base_cloud_mult=1.35,
        ground_blast_mult=1.25, shake_amp=0.60,
        mass_kg=1665.0, diam_m=0.508, cd=0.34, g_max=25.0,
        lift_q_gain=3.8e-4, range_km=75.0, warhead_kg=133.0),
    MissileVariant(
        id="9m96", label="9M96E2", blurb="AGILE DUAL-PULSE - THIN AND CLEAN",
        length_m=4.75, eject_v0=32.0, ignite_delay=0.7,
        boost_accel=230.0, burns=((0.0, 6.0), (11.0, 15.0)),
        tilt_rate_deg=14.0, tilt_max_deg=42.0,
        flame_len_m=4.3, flame_core=(1.0, 0.99, 0.92),
        flame_edge=(1.0, 0.59, 0.16),
        smoke_fresh=(0.95, 0.94, 0.89), smoke_old=(0.73, 0.74, 0.74),
        smoke_rate=34.0, smoke_size=(3.0, 27.0), column_persist_s=170.0,
        fireball_scale=0.6, life_s=30.0,
        smoke_per_m=0.72, width_mult=0.44, base_cloud_mult=0.48,
        ground_blast_mult=0.36, shake_amp=0.22,
        mass_kg=420.0, diam_m=0.240, cd=0.30, g_max=60.0,
        lift_q_gain=6.5e-4, range_km=120.0, warhead_kg=24.0),
    MissileVariant(
        id="40n6", label="40N6", blurb="THE 400 KM MONSTER - HUGE COLUMN",
        length_m=8.8, eject_v0=33.0, ignite_delay=1.0,
        boost_accel=155.0, burns=((0.0, 11.0),),
        tilt_rate_deg=5.0, tilt_max_deg=26.0,
        flame_len_m=11.0, flame_core=(1.0, 0.98, 0.88),
        flame_edge=(1.0, 0.55, 0.12),
        smoke_fresh=(0.92, 0.91, 0.84), smoke_old=(0.67, 0.70, 0.71),
        smoke_rate=76.0, smoke_size=(10.0, 72.0), column_persist_s=330.0,
        fireball_scale=1.3, life_s=45.0,
        smoke_per_m=3.30, width_mult=1.60, base_cloud_mult=2.10,
        ground_blast_mult=2.30, shake_amp=1.10,
        mass_kg=1893.0, diam_m=0.519, cd=0.32, g_max=20.0,
        lift_q_gain=3.5e-4, range_km=380.0, warhead_kg=180.0),
    MissileVariant(
        # docs/research/ammo_expansion_2026-07-17.md section 3.
        id="iskander", label="ISKANDER-M",
        blurb="9M723 QUASI-BALLISTIC - FLAT, FAST, 700 KG",
        length_m=7.3, eject_v0=14.0, ignite_delay=0.3,
        boost_accel=75.0, burns=((0.0, 42.0),),
        tilt_rate_deg=16.0, tilt_max_deg=52.0,
        flame_len_m=8.5, flame_core=(1.0, 0.96, 0.84),
        flame_edge=(1.0, 0.52, 0.12),
        smoke_fresh=(0.85, 0.84, 0.79), smoke_old=(0.62, 0.63, 0.62),
        smoke_rate=70.0, smoke_size=(6.0, 44.0), column_persist_s=200.0,
        fireball_scale=1.1, life_s=60.0,
        smoke_per_m=2.60, width_mult=1.30, base_cloud_mult=1.60,
        ground_blast_mult=1.70, shake_amp=0.95,
        mass_kg=3800.0, diam_m=0.92, cd=0.30, g_max=30.0,
        lift_q_gain=4.5e-4, range_km=500.0, warhead_kg=700.0),
)

VARIANT_BY_ID = {v.id: v for v in VARIANTS}

# Light valley wind for the drifting column: research preset 2-4 m/s with
# ~0.5 m/s buoyant rise (60-120 m drift after 30 s checks out).  This is
# the FALLBACK when the scene has no baked wind profile — with one, every
# emission asks _wind() for the measured flow at its own altitude.
WIND = np.array([2.4, 0.0, 1.0], dtype=np.float32)


def _wind(fx, y: float) -> np.ndarray:
    """Ambient wind (3,) at scene height y: the fx's measured profile
    when it carries one (CinematicEffects), else the legacy constant."""
    fn = getattr(fx, "wind_at", None)
    return fn(float(y)) if fn is not None else WIND.astype(np.float64)


class ScriptedLaunch:
    """One missile flying its variant's cold-launch script (no guidance)."""

    def __init__(self, variant: MissileVariant, pad_pos, away_yaw: float,
                 tube_top: float):
        self.variant = variant
        self.t = 0.0
        self.pos = np.array([pad_pos[0], pad_pos[1] + tube_top, pad_pos[2]],
                            dtype=np.float64)
        self.vel = np.array([0.0, variant.eject_v0, 0.0], dtype=np.float64)
        self.away_yaw = away_yaw
        self.tilt = 0.0
        self.ignited = False
        self.done = False
        self._flame_carry = 0.0
        self._last_smoke_pos = None
        self._next_clump = 0.0       # path meters until the next billow
        self._bridge_carry = 0.0
        self._veil_carry = 0.0
        self._jet_carry = 0.0
        self._spew_carry = 0.0       # pad wall-jet feed while the round is low
        self._path_m = 0.0
        self._alt0 = float(pad_pos[1])
        self._pad0 = np.array(pad_pos, dtype=np.float64)
        self._blast_done = False
        self._roll_done = False

    # ------------------------------------------------------------- physics

    @property
    def axis(self) -> np.ndarray:
        s, c = math.sin(self.away_yaw), math.cos(self.away_yaw)
        st, ct = math.sin(self.tilt), math.cos(self.tilt)
        return np.array([s * st, ct, c * st], dtype=np.float64)

    def burning(self) -> bool:
        if not self.ignited:
            return False
        tb = self.t - self.variant.ignite_delay
        return any(a <= tb < b for a, b in self.variant.burns)

    def step(self, dt: float, events: list) -> None:
        """Advance; appends ('ignite', pos) when the motor lights."""
        if self.done:
            return
        v = self.variant
        self.t += dt
        if self.t >= v.life_s:
            self.done = True
            return
        if not self.ignited:
            self.vel[1] -= GRAVITY * dt
            self.pos += self.vel * dt
            if self.t >= v.ignite_delay:
                self.ignited = True
                events.append(("ignite", self.pos.copy()))
        elif not self._roll_done:
            # Exhaust hits the pad an instant after light-off: fast dust
            # sheet first, then the slower rolling vortex ring over it.
            if not self._blast_done and self.t >= v.ignite_delay + 0.08:
                self._blast_done = True
                events.append(("pad_blast", self._pad0.copy()))
            if self.t >= v.ignite_delay + 0.26:
                self._roll_done = True
                events.append(("pad_roll", self._pad0.copy()))
            self.tilt = min(math.radians(v.tilt_max_deg),
                            self.tilt + math.radians(v.tilt_rate_deg) * dt)
            if self.burning():
                self.vel += self.axis * (v.boost_accel * dt)
            self.vel[1] -= GRAVITY * dt
            self.pos += self.vel * dt
            return
        else:
            self.tilt = min(math.radians(v.tilt_max_deg),
                            self.tilt + math.radians(v.tilt_rate_deg) * dt)
            if self.burning():
                self.vel += self.axis * (v.boost_accel * dt)
            self.vel[1] -= GRAVITY * dt
            self.pos += self.vel * dt

    def heading(self) -> np.ndarray:
        n = float(np.linalg.norm(self.vel))
        return (self.vel / n if n > 1e-6
                else np.array([0.0, 1.0, 0.0]))

    # ------------------------------------------------------------ emission

    def emit(self, fx, dt: float) -> None:
        """Per-sim-step particle emission into ``fx`` (Effects) pools.

        Four layers per the GPT-5.6 xhigh particle consult (all velocities
        are relative to the ambient wind, which the pool's wind-relative
        drag preserves): a hot stretched additive core, a decelerating
        smoke JET off the nozzle, clumped long-lived BILLOWS laid along
        the flown path (clumps, not evenly spaced dots), and a faint
        persistent VEIL that stands in for the minutes-old column."""
        if self.done or not self.ignited:
            return
        v = self.variant
        h = self.heading()
        tail = self.pos - h * (v.length_m * 0.55)
        rel_alt = max(0.0, float(tail[1]) - self._alt0)
        # Dissipation: the column must THIN OUT at a decent distance
        # instead of standing fresh from pad to apogee (user report
        # 2026-07-16) — drier, windier air aloft shreds smoke faster, so
        # particle LIFETIMES shrink with altitude while the pad-level
        # column keeps its minutes-long hang.
        ls = 1.0 / (1.0 + (rel_alt / 1200.0) ** 1.6)
        r = fx.rng
        self._pad_spew(fx, rel_alt, dt, r)
        if self.burning():
            # Hot additive core: fast back-flung stretched sprites + the
            # strung flame (25-45 Hz flicker + ~8 Hz breathing).
            slow = 1.0 + 0.2 * math.sin(self.t * 2.0 * math.pi * 8.0)
            self._flame_carry += dt * 160.0 * slow
            n_flame = int(self._flame_carry)
            self._flame_carry -= n_flame
            for _ in range(min(n_flame, 4)):
                back = r.uniform(0.0, v.flame_len_m)
                p = tail - h * back
                frac = back / max(v.flame_len_m, 1e-6)
                col = tuple(np.array(v.flame_core) * (1 - frac)
                            + np.array(v.flame_edge) * frac)
                size = (1.0 - 0.55 * frac) * (0.16 * v.flame_len_m)
                fx.fire.emit(1, p, 0.25, -h * 95.0, 6.0, (0.08, 0.24),
                             (size * 0.5, size * 1.6), (col, col), r,
                             stretch=0.025)
            # Glow: the faint bright dot still visible at 10 km.
            fx.fire.emit(1, tail - h * v.flame_len_m * 0.3, 0.1,
                         (0.0, 0.0, 0.0), 0.0, (0.05, 0.09),
                         (v.flame_len_m * 1.5, v.flame_len_m * 1.9),
                         ((0.45, 0.40, 0.30), (0.4, 0.32, 0.22)), r)
        tb = self.t - v.ignite_delay
        outgassing = self.burning() or any(
            b <= tb < b + 0.6 for _a, b in v.burns)
        if not outgassing:
            self._last_smoke_pos = None
            return
        if self._last_smoke_pos is None:
            self._last_smoke_pos = tail.copy()
        seg = tail - self._last_smoke_pos
        dist = float(np.linalg.norm(seg))
        if dist <= 1e-6:
            return
        seg_dir = seg / dist
        wind = _wind(fx, tail[1])    # measured flow AT THIS altitude
        # Altitude taper: the first ~2 km of column carries the scene.
        taper = 1.0 / (1.0 + (rel_alt / 900.0) ** 2)
        wm = v.width_mult
        # Fresh column near the pad is FATTER (slow climb, dense efflux);
        # it thins as speed builds and propellant drops (user: 'bigger in
        # the beginning').  +90% width at the pad, gone by ~600 m up.
        wm = wm * (1.0 + 0.9 * math.exp(-rel_alt / 300.0))
        rate = (v.smoke_per_m / 1.8) * taper

        # JET: hot-to-cool smoke thrown backwards, decelerating under the
        # wind-relative drag (36 m/s -> ~6 m/s in 2 s at drag 0.90).
        self._jet_carry += dist * 0.5 * taper * (v.smoke_per_m / 1.8)
        n_jet = int(self._jet_carry)
        self._jet_carry -= n_jet
        for _ in range(n_jet):
            radial = np.cross(h, r.standard_normal(3))
            rn = np.linalg.norm(radial)
            radial = radial / rn * r.uniform(8.0, 12.0) if rn > 1e-6 else 0.0
            jl = max(ls, 0.35)
            fx.smoke.emit(1, tail - h * r.uniform(1.0, 1.5), 0.5,
                          wind - h * 36.0 + radial, 2.0,
                          (6.0 * jl, 10.0 * jl),
                          (0.6 * wm, 7.5 * wm),
                          (v.smoke_fresh, v.smoke_old), r,
                          alpha01=(0.80, 0.08), fade_in=0.06, stretch=0.02)

        # BILLOWS: clumps of 3-5 sharing a center + eddy, gap 3.0-5.5 m
        # (scaled by the variant's smoke budget) — billows, not beads.
        gap_scale = 1.8 / max(v.smoke_per_m, 0.1)
        self._path_m += dist
        while self._path_m >= self._next_clump:
            t_along = 1.0 - (self._path_m - self._next_clump) / dist
            t_along = min(max(t_along, 0.0), 1.0)
            center = (self._last_smoke_pos + seg * t_along
                      + np.cross(seg_dir, r.standard_normal(3)) * 0.8)
            eddy = r.normal(0.0, 0.6, 3).astype(np.float64)
            for _ in range(int(r.integers(3, 6))):
                fx.smoke.emit(
                    1, center, 1.2,
                    wind + eddy + np.array([0.0, 0.15, 0.0]), 0.4,
                    (max(8.0, 40.0 * ls), max(12.0, 60.0 * ls)),
                    (v.smoke_size[0] * wm / 1.0, v.smoke_size[1] * wm),
                    (v.smoke_fresh, v.smoke_old), r,
                    alpha01=(0.55, 0.03), fade_in=0.14)
            self._next_clump += r.uniform(3.0, 5.5) * gap_scale / taper \
                if taper > 1e-3 else 1e9

        # VEIL: sparse huge faint puffs with the variant's full persistence.
        self._veil_carry += dist * 0.16 * rate
        n_veil = int(self._veil_carry)
        self._veil_carry -= n_veil
        # Veil persistence collapses fastest with altitude (ls^2): the
        # minutes-long hang is a PAD-LEVEL phenomenon; up high the thin
        # column shears away in tens of seconds.
        vp = max(10.0, v.column_persist_s * ls * ls)
        for k in range(n_veil):
            p = self._last_smoke_pos + seg * ((k + 0.5) / max(n_veil, 1))
            fx.smoke.emit(1, p, 2.5,
                          wind + np.array([0.0, 0.15, 0.0]), 0.6,
                          (vp * 0.7, vp),
                          (6.0 * wm, 40.0 * wm),
                          (v.smoke_old, v.smoke_old), r,
                          alpha01=(0.20, 0.02), fade_in=0.20)
        self._last_smoke_pos = tail.copy()

    def _pad_spew(self, fx, rel_alt: float, dt: float, r) -> None:
        """Sustained pad wall-jet while the booster is still LOW: the
        exhaust keeps slamming the pad and feeding the ground cloud, so
        big slow billows spew outward for the first seconds instead of
        one instant puff (user report: the blast was 'a tiny little
        effect that disappears immediately').  Two feeds per burst: a
        bright efflux boil climbing off the pad and a dusty skirt
        hugging it, both long-lived so the cloud LINGERS and drifts."""
        if rel_alt >= 260.0 or not self.burning():
            return
        v = self.variant
        gb = v.ground_blast_mult
        spew = 1.0 - rel_alt / 260.0
        self._spew_carry += dt * 72.0 * gb * spew
        n = int(self._spew_carry)
        self._spew_carry -= n
        if n == 0:
            return
        origin = self._pad0 + np.array([0.0, 2.0, 0.0])
        n_boil = (n + 1) // 2
        idx = fx.smoke.emit(n_boil, origin, 4.5,
                            (0.0, 6.5 * spew + 1.5, 0.0), 2.0,
                            (16.0, 34.0), (5.0, 38.0),
                            (v.smoke_fresh, v.smoke_old), r,
                            alpha01=(0.60, 0.04), fade_in=0.12)
        if len(idx):
            ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
            speed = r.uniform(6.0, 16.0, len(idx)) * spew
            fx.smoke.vel[idx, 0] += (np.sin(ang) * speed).astype(np.float32)
            fx.smoke.vel[idx, 2] += (np.cos(ang) * speed).astype(np.float32)
        idx = fx.smoke.emit(n - n_boil, origin, 5.5,
                            (0.0, 1.6, 0.0), 1.0,
                            (20.0, 40.0), (8.0, 50.0),
                            ((0.62, 0.58, 0.51), (0.48, 0.46, 0.42)), r,
                            alpha01=(0.50, 0.03), fade_in=0.18)
        if len(idx):
            ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
            speed = r.uniform(10.0, 26.0, len(idx)) * spew
            fx.smoke.vel[idx, 0] += (np.sin(ang) * speed).astype(np.float32)
            fx.smoke.vel[idx, 2] += (np.cos(ang) * speed).astype(np.float32)

    def ignition_fx(self, fx, pos) -> None:
        """Light-off: a variant-SCALED fireball built from the pools (the
        engine's stock fireball has one fixed size — a 9M96 flash must be
        half a 40N6's). Research: fireball 6-11x missile diameter, flash
        0.1-0.2 s, core 255,250,225 -> edge 255,125,25."""
        v = self.variant
        r = fx.rng
        d_fb = 4.4 * v.fireball_scale
        fx.fire.emit(2, pos, 0.3, (0.0, 0.0, 0.0), 0.0, (0.10, 0.16),
                     (d_fb * 1.6, d_fb * 2.1),
                     ((1.0, 0.98, 0.88), (1.0, 0.9, 0.6)), r)
        fx.fire.emit(int(20 * v.fireball_scale) + 6, pos,
                     d_fb * 0.28, (0.0, 2.0, 0.0), 5.0, (0.22, 0.48),
                     (d_fb * 0.5, d_fb * 1.3),
                     ((1.0, 0.85, 0.45), (1.0, 0.49, 0.10)), r)
        fx.smoke.emit(int(10 * v.fireball_scale) + 4, pos, d_fb * 0.4,
                      _wind(fx, pos[1]) + np.array([0.0, 2.5, 0.0]),
                      2.5, (3.0, 7.0),
                      (d_fb * 0.6, d_fb * 2.6),
                      (v.smoke_fresh, v.smoke_old), r,
                      alpha01=(0.7, 0.05), fade_in=0.05)

    def pad_blast_fx(self, fx, pad_pos) -> None:
        """Exhaust hits the pad: a TEL-swallowing wall jet, not specks.

        Three parts (user: the old ring was 'tiny brown particles'):
        the fast stretched dust sheet skating outward, a WHITE steam/
        efflux surge — cold-launch pads blow mostly bright exhaust
        product, dust only rims it — and a slow fat BASE CLOUD that
        buries the launcher for ~15 s (research: 16-26 m base cloud)."""
        v = self.variant
        gb = v.ground_blast_mult
        r = fx.rng
        origin = np.array([pad_pos[0], pad_pos[1] + 1.0, pad_pos[2]])
        # 1) Dust sheet: fast, ground-hugging, velocity-stretched.
        idx = fx.smoke.emit(int(110 * gb), origin, 2.5, (0.0, 1.2, 0.0),
                            0.6, (2.5, 5.0), (2.5, 18.0),
                            ((0.60, 0.55, 0.47), (0.46, 0.43, 0.38)), r,
                            alpha01=(0.8, 0.05), fade_in=0.04,
                            stretch=0.035)
        if len(idx):
            ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
            speed = r.uniform(36.0, 58.0, len(idx))
            fx.smoke.vel[idx, 0] = (np.sin(ang) * speed).astype(np.float32)
            fx.smoke.vel[idx, 2] = (np.cos(ang) * speed).astype(np.float32)
            fx.smoke.vel[idx, 1] = r.uniform(0.5, 2.2, len(idx)) \
                .astype(np.float32)
        # 2) White efflux surge boiling up around the tube.
        fx.smoke.emit(int(46 * gb), origin + np.array([0.0, 2.0, 0.0]),
                      3.5, (0.0, 11.0, 0.0), 4.0, (7.0, 14.0),
                      (4.0, 26.0), (v.smoke_fresh, v.smoke_old), r,
                      alpha01=(0.85, 0.06), fade_in=0.05)
        # 3) Base cloud: slow, fat, buries the TEL and LINGERS — real pad
        # clouds stand for the better part of a minute before the valley
        # wind walks them away (user report: 'disappears immediately').
        fx.smoke.emit(int(44 * gb), origin + np.array([0.0, 3.0, 0.0]),
                      5.0, _wind(fx, origin[1]) + np.array([0.0, 2.0, 0.0]),
                      2.0, (22.0, 40.0), (9.0, 42.0),
                      (v.smoke_fresh, v.smoke_old), r,
                      alpha01=(0.55, 0.04), fade_in=0.12)

    def pad_roll_fx(self, fx, pad_pos) -> None:
        """0.18 s later: the slower, HIGHER ring that rolls over the dust
        sheet (the vortex read), plus a lingering ground haze skirt."""
        v = self.variant
        gb = v.ground_blast_mult
        r = fx.rng
        origin = np.array([pad_pos[0], pad_pos[1] + 2.5, pad_pos[2]])
        idx = fx.smoke.emit(int(80 * gb), origin, 3.0, (0.0, 9.0, 0.0),
                            1.2, (6.0, 11.0), (4.0, 24.0),
                            ((0.72, 0.68, 0.62), (0.52, 0.50, 0.48)), r,
                            alpha01=(0.7, 0.05), fade_in=0.08)
        if len(idx):
            ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
            speed = r.uniform(24.0, 40.0, len(idx))
            swirl = r.uniform(-6.0, 6.0, len(idx))
            fx.smoke.vel[idx, 0] = (np.sin(ang) * speed
                                    + np.cos(ang) * swirl).astype(np.float32)
            fx.smoke.vel[idx, 2] = (np.cos(ang) * speed
                                    - np.sin(ang) * swirl).astype(np.float32)
            fx.smoke.vel[idx, 1] = r.uniform(7.0, 12.0, len(idx)) \
                .astype(np.float32)
        # Ground haze skirt: wide, slow, stays long after the rings die.
        fx.smoke.emit(int(30 * gb), origin, 8.0,
                      _wind(fx, origin[1]) + np.array([0.0, 0.8, 0.0]), 1.2,
                      (30.0, 55.0), (14.0, 48.0),
                      ((0.66, 0.63, 0.58), (0.50, 0.49, 0.47)), r,
                      alpha01=(0.32, 0.02), fade_in=0.2)

    def eject_fx(self, fx, mouth, pad_y: float) -> None:
        """Cold eject: UNLIT pale gas ring at the canister mouth + a dust
        wash on the pad — no combustion colors.  Scaled by the variant's
        base-cloud multiplier (research: 8-14 m for 9M96, 18-26 m 40N6)."""
        v = self.variant
        bm = v.base_cloud_mult
        r = fx.rng
        fx.smoke.emit(int(24 * bm) + 6, mouth, 1.2 * bm,
                      (0.0, 8.0, 0.0), 3.2, (2.0, 3.5),
                      (2.2 * bm, 8.5 * bm),
                      ((0.74, 0.72, 0.66), (0.60, 0.60, 0.58)), r,
                      alpha01=(0.65, 0.04), fade_in=0.06)
        idx = fx.smoke.emit(int(12 * bm) + 2,
                            np.array([mouth[0], pad_y + 0.6, mouth[2]]),
                            1.2, (0.0, 0.8, 0.0), 0.5, (1.5, 3.0),
                            (1.8 * bm, 5.0 * bm),
                            ((0.55, 0.50, 0.42), (0.42, 0.39, 0.34)), r,
                            alpha01=(0.55, 0.04), fade_in=0.08)
        if len(idx):
            ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
            speed = r.uniform(5.0, 11.0, len(idx))
            fx.smoke.vel[idx, 0] = (np.sin(ang) * speed).astype(np.float32)
            fx.smoke.vel[idx, 2] = (np.cos(ang) * speed).astype(np.float32)



# ----------------------------------------------------- universal T-targeting

RHO0 = 1.225               # sea-level air density (kg/m^3)
SCALE_H = 8500.0           # exponential-atmosphere scale height (m)
SAM_TWIN_DT = 0.1          # planning twin step (segment hit tests keep
                           # coarse strides exact; 0.05 doubled the
                           # L-press cost for no measured accuracy)
SAM_HIT_M = 25.0           # twin counts the mark reached inside this
SAM_CLEAR_M = 250.0        # glide line must clear terrain by this much
SAM_GATE_UP_M = 150.0      # extra climb bias over the binding crest
SAM_CLEAR_ENDS_M = 800.0   # ...except this close to launch/impact
SAM_SLEW_DEG_S = 55.0      # cold-launch TVC flip rate (drawn + thrust)
SAM_ROUTE_STEP_M = 200.0   # terrain profile sampling along the route
SAM_GATE_R = 300.0         # gate waypoints count as passed inside this
SAM_TAU_GROWTH = 1.15      # fastest-route search: tau bump per retry
SAM_DIRECT_TAU_MULT = 2.2  # direct tau ceiling before gates are tried


def _air_rho(y_asl: float) -> float:
    return RHO0 * math.exp(-max(y_asl, 0.0) / SCALE_H)


def _seg_dist(a: np.ndarray, b: np.ndarray, p: np.ndarray) -> float:
    """Distance from point ``p`` to segment a->b (per-tick paths move
    50-80 m — a point-sample proximity test flies straight THROUGH
    the mark between ticks)."""
    seg = b - a
    n2 = float(np.dot(seg, seg))
    t = float(np.dot(p - a, seg)) / n2 if n2 > 1e-12 else 0.0
    t = min(max(t, 0.0), 1.0)
    return float(np.linalg.norm(p - (a + seg * t)))


class GuidedLaunch(ScriptedLaunch):
    """A pad round flying to a designated GROUND mark (T-targeting).

    Same launch theater and particle art as ScriptedLaunch — this class
    only replaces the kinematics with a flight computer: PIECEWISE
    LAMBERT.  Each leg flies the proven drag-aware Lambert law (v_req =
    D/tau + g*tau/2*up; thrust dead along the velocity-to-be-gained
    while the motor burns, q-limited aero steering on the coast) at the
    smallest arrival time a forward twin of the law can actually fly.
    When the direct leg would need silly loft to clear terrain (a pure
    Lambert answer to a valley wall is stratospheric — measured 180 s
    for a 30 km shot), the planner inserts a GATE waypoint above the
    binding crest and flies fast leg -> gate -> fast dive instead.
    Zero RNG; ``fx.rng`` never touches the trajectory."""

    def __init__(self, variant: MissileVariant, pad_pos, away_yaw: float,
                 tube_top: float, target, ground_h, origin_alt: float = 0.0):
        super().__init__(variant, pad_pos, away_yaw, tube_top)
        tx, tz = float(target[0]), float(target[2])
        self.target = np.array([tx, float(ground_h(tx, tz)), tz],
                               dtype=np.float64)
        self.ground_h = ground_h
        self._origin_alt = float(origin_alt)   # scene y -> ASL for rho
        self._axis_g = np.array([0.0, 1.0, 0.0])   # slewed attitude
        self._t_ign = None
        self.impacted = False
        self._legs = self._plan()          # [(aim, tau, is_final)] | None
        self._leg_i = 0
        self._leg_t0 = 0.0                 # flight clock when leg began
        self.twin_tof = -1.0
        if self._legs is not None:
            # The coarse search twin can pass plans the 1/120 live
            # flight misses (measured 4.9 km divergence).  step() is
            # deterministic, so flying THE ACTUAL step() on saved state
            # makes the verdict bit-exact for the real flight.
            self._legs = self._verified_legs(self._legs)

    def _verified_legs(self, legs):
        """Verify (and if needed nudge) a plan at live resolution.
        Near-misses can be early OR late, so the final-leg clock walks
        both directions before the expensive fine replan fallback."""
        base = legs[-1][1]
        for mult in (1.0, 1.1, 0.92, 1.21, 0.85, 1.35):
            aim, _tau, fin = legs[-1]
            legs[-1] = (aim, base * mult, fin)
            self._legs = legs
            ok, tof = self._verify_full()
            if ok:
                self.twin_tof = tof
                return legs
        # Last resort: re-search with the twin AT live resolution
        # (rare; a 45 km 48N6 shot needed it in the probe).
        global SAM_TWIN_DT
        coarse = SAM_TWIN_DT
        SAM_TWIN_DT = 1.0 / 120.0
        try:
            legs2 = self._plan_search()
        finally:
            SAM_TWIN_DT = coarse
        if legs2 is not None:
            self._legs = legs2
            ok, tof = self._verify_full()
            if ok:
                self.twin_tof = tof
                return legs2
        return None

    @property
    def feasible(self) -> bool:
        return self._legs is not None

    # The scripted parent's axis is a yaw/tilt script; the guided round
    # slews a real attitude with its velocity vector.
    @property
    def axis(self) -> np.ndarray:              # type: ignore[override]
        return self._axis_g

    def _beta(self) -> float:
        v = self.variant
        area = math.pi * (v.diam_m * 0.5) ** 2
        return v.cd * area / v.mass_kg

    def _lat_max(self, speed: float, y_asl: float) -> float:
        """Steering authority (m/s^2): q-scaled lift, g-ceiling capped."""
        v = self.variant
        q = 0.5 * _air_rho(y_asl) * speed * speed
        return min(v.g_max * GRAVITY, v.lift_q_gain * q * GRAVITY)

    # ---------------------------------------------------------- planning

    def _verify_full(self):
        """Fly the real step() at the game's 1/120 on saved state; the
        flight is deterministic so this IS the live outcome."""
        saved = (self.pos.copy(), self.vel.copy(), self.t, self.ignited,
                 self._t_ign, self._leg_i, self._leg_t0, self.done,
                 self.impacted, self._axis_g.copy(), self._blast_done,
                 self._roll_done, self._last_smoke_pos,
                 getattr(self, "_leg_start", None))
        self.twin_tof = 1e9                # disarm the lost-round guard
        cap = sum(leg[1] for leg in self._legs) * 2.0 + 60.0
        sink: list = []
        while not self.done and self.t < cap:
            self.step(1.0 / 120.0, sink)
        ok = (self.impacted and float(
            np.linalg.norm(self.pos - self.target)) <= SAM_HIT_M)
        tof = self.t
        (self.pos, self.vel, self.t, self.ignited, self._t_ign,
         self._leg_i, self._leg_t0, self.done, self.impacted,
         self._axis_g, self._blast_done, self._roll_done,
         self._last_smoke_pos, leg_start) = saved
        if leg_start is None:
            if hasattr(self, "_leg_start"):
                del self._leg_start
        else:
            self._leg_start = leg_start
        return ok, tof

    def _plan(self):
        rng_m = math.hypot(self.target[0] - self.pos[0],
                           self.target[2] - self.pos[2])
        if rng_m > self.variant.range_km * 1000.0:
            return None
        return self._plan_search()

    def _plan_search(self):
        v = self.variant
        res = self._plan_from(self.pos.copy(),
                              np.array([0.0, v.eject_v0, 0.0]),
                              -v.ignite_delay, self.target,
                              is_final=True, depth=0)
        return res[0] if res is not None else None

    def _plan_from(self, pos, vel, t_off, goal, is_final, depth):
        """Plan legs from a flight state.  Returns (legs, end_pos,
        end_vel, end_t_off) or None.  Direct Lambert first at growing
        tau; once tau would mean silly loft, split at the binding crest
        (depth-limited) and keep both sub-legs fast."""
        dist = float(np.linalg.norm(goal - pos))
        floor = max(6.0, dist / 900.0)     # can't beat ~Mach 2.6 average
        tau = floor
        tried_gate = False
        for k in range(26):
            res = self._twin_leg(pos, vel, t_off, goal, tau, is_final)
            if res is not None:
                legs = [(np.asarray(goal, dtype=np.float64), tau,
                         is_final)]
                return legs, res[0], res[1], res[2]
            if (not tried_gate and depth < 2
                    and tau > floor * SAM_DIRECT_TAU_MULT):
                tried_gate = True
                gate = self._binding_gate(pos, goal)
                if gate is not None:
                    r1 = self._plan_from(pos, vel, t_off, gate,
                                         is_final=False, depth=depth + 1)
                    if r1 is not None:
                        legs1, p1, v1, t1 = r1
                        r2 = self._plan_from(p1, v1, t1, goal,
                                             is_final=is_final,
                                             depth=depth + 1)
                        if r2 is not None:
                            legs2, p2, v2, t2 = r2
                            return legs1 + legs2, p2, v2, t2
            # Uniform ladder: feasibility is NOT monotone in tau, an
            # accelerating ladder skipped 48 s windows into 275 s plans
            # (measured).
            tau *= SAM_TAU_GROWTH
        return None

    def _binding_gate(self, pos, goal):
        """Waypoint above the crest that most blocks the pos->goal
        chord, or None when the chord is clear."""
        total = math.hypot(goal[0] - pos[0], goal[2] - pos[2])
        n = max(3, min(400, int(total / SAM_ROUTE_STEP_M)))
        best_def, best = 0.0, None
        for i in range(1, n):
            f = i / n
            s = f * total
            if s < SAM_CLEAR_ENDS_M or total - s < SAM_CLEAR_ENDS_M:
                continue
            x = pos[0] + (goal[0] - pos[0]) * f
            z = pos[2] + (goal[2] - pos[2]) * f
            g = float(self.ground_h(float(x), float(z)))
            if not np.isfinite(g):
                continue
            line = pos[1] + (goal[1] - pos[1]) * f
            deficit = (g + SAM_CLEAR_M) - line
            if deficit > best_def:
                best_def = deficit
                best = np.array([x, g + SAM_CLEAR_M + SAM_GATE_UP_M, z])
        return best

    def _twin_leg(self, pos, vel, t_off, goal, tau, is_final):
        """Fly one Lambert leg at coarse dt.  Success -> (end_pos,
        end_vel, end_t_off); None on terrain/short/timeout."""
        pos = pos.copy()
        vel = vel.copy()
        t = 0.0
        tick = 0
        hd_total = math.hypot(goal[0] - pos[0], goal[2] - pos[2])
        start = pos.copy()
        while t < tau + 3.0:
            prev = pos.copy()
            if t_off + t >= 0.0:
                pos, vel = self._fly_tick(pos, vel, t_off + t, goal,
                                          tau - t, SAM_TWIN_DT)
            else:                          # unlit hang out of the tube
                vel = vel + np.array([0.0, -GRAVITY * SAM_TWIN_DT, 0.0])
                pos = pos + vel * SAM_TWIN_DT
            t += SAM_TWIN_DT
            tick += 1
            hit_r = SAM_HIT_M if is_final else SAM_GATE_R
            if _seg_dist(prev, pos, goal) < hit_r:
                return pos, vel, t_off + t
            if not is_final:
                # Passing the gate's along-track plane also counts.
                u = goal - start
                u[1] = 0.0
                nu = float(np.linalg.norm(u))
                if nu > 1e-6 and float(np.dot(pos - goal, u / nu)) > 0.0:
                    return pos, vel, t_off + t
            # Terrain every 4th tick, ends exempted.
            dx = math.hypot(goal[0] - pos[0], goal[2] - pos[2])
            end_d = min(hd_total - dx, dx)
            if (tick % 4 == 0 and end_d > SAM_CLEAR_ENDS_M
                    and t_off + t > 2.0):
                g = float(self.ground_h(float(pos[0]), float(pos[2])))
                if np.isfinite(g) and pos[1] < g + 40.0:
                    return None            # flew into a ridge
            if is_final and vel[1] < 0.0 and pos[1] < goal[1] - 150.0:
                return None                # into the ground short
        return None

    # ------------------------------------------------------------ the law

    def _fly_tick(self, pos, vel, t_glob, goal, tau_rem, dt):
        """One tick of the Lambert law (shared by twin and live)."""
        v = self.variant
        tau_rem = max(tau_rem, 0.5)
        v_req = ((goal - pos) / tau_rem
                 + np.array([0.0, 0.5 * GRAVITY * tau_rem, 0.0]))
        speed = float(np.linalg.norm(vel))
        y_asl = float(pos[1]) + self._origin_alt
        if any(a <= t_glob < b for a, b in v.burns):
            vg = v_req - vel
            nvg = float(np.linalg.norm(vg))
            if nvg > 1e-6:
                # TVC flip: thrust walks from vertical onto the demand
                # at the real cold-launch slam rate, then rides it.
                want = vg / nvg
                lim = math.radians(SAM_SLEW_DEG_S) * max(t_glob, 0.0)
                up = np.array([0.0, 1.0, 0.0])
                cosang = float(np.clip(np.dot(up, want), -1.0, 1.0))
                ang = math.acos(cosang)
                if ang > lim:
                    f = lim / ang
                    want = up * (1.0 - f) + want * f
                    want = want / float(np.linalg.norm(want))
                vel = vel + want * (v.boost_accel * dt)
        elif speed > 1e-6:
            # Coast: q-limited aero steering toward the Lambert demand.
            want = v_req / max(float(np.linalg.norm(v_req)), 1e-9)
            have = vel / speed
            cosang = float(np.clip(np.dot(have, want), -1.0, 1.0))
            ang = math.acos(cosang)
            max_ang = self._lat_max(speed, y_asl) / max(speed, 1.0) * dt
            if ang > 1e-6:
                f = min(1.0, max_ang / ang)
                new_dir = have * (1.0 - f) + want * f
                new_dir = new_dir / float(np.linalg.norm(new_dir))
                vel = new_dir * speed
        # Gravity + drag (exponential atmosphere).
        vel = vel + np.array([0.0, -GRAVITY * dt, 0.0])
        speed = float(np.linalg.norm(vel))
        if speed > 1e-6:
            drag = 0.5 * _air_rho(y_asl) * speed * self._beta()
            vel = vel * max(0.0, 1.0 - drag * dt)
        return pos + vel * dt, vel

    # ------------------------------------------------------- live flight

    def step(self, dt: float, events: list) -> None:
        if self.done:
            return
        v = self.variant
        self.t += dt
        if not self.ignited:
            self.vel[1] -= GRAVITY * dt
            self.pos += self.vel * dt
            if self.t >= v.ignite_delay:
                self.ignited = True
                self._t_ign = self.t
                events.append(("ignite", self.pos.copy()))
            return
        if not self._blast_done and self.t >= v.ignite_delay + 0.08:
            self._blast_done = True
            events.append(("pad_blast", self._pad0.copy()))
        if not self._roll_done and self.t >= v.ignite_delay + 0.26:
            self._roll_done = True
            events.append(("pad_roll", self._pad0.copy()))
        tf = self.t - self._t_ign
        aim, tau, is_final = self._legs[self._leg_i]
        t_leg = tf - self._leg_t0
        if not hasattr(self, "_leg_start"):
            self._leg_start = self.pos.copy()
        prev = self.pos.copy()
        self.pos, self.vel = self._fly_tick(self.pos, self.vel, tf, aim,
                                            tau - t_leg, dt)
        sp = float(np.linalg.norm(self.vel))
        if sp > 5.0:
            self._axis_g = self.vel / sp
        # Gate passage -> next leg (SAME criterion as the twin: sphere
        # or the along-track plane measured from the LEG START — a
        # mismatched plane normal made live flights switch legs off the
        # twin's plan and drift 250+ m at 45 km, measured).
        if not is_final:
            u = aim - self._leg_start
            u[1] = 0.0
            nu = float(np.linalg.norm(u))
            passed = (_seg_dist(prev, self.pos, aim) < SAM_GATE_R
                      or (nu > 1e-6
                          and float(np.dot(self.pos - aim, u / nu)) > 0.0))
            if passed or t_leg > tau + 5.0:
                self._leg_i = min(self._leg_i + 1, len(self._legs) - 1)
                self._leg_t0 = tf
                self._leg_start = self.pos.copy()
            return
        # Impact: mark proximity (segment test) or terrain crossing.
        if _seg_dist(prev, self.pos, self.target) < 15.0:
            self.pos = self.target.copy()
            events.append(("impact", self.pos.copy()))
            self.impacted = True
            self.done = True
            return
        if self.vel[1] < 0.0:
            g = float(self.ground_h(float(self.pos[0]),
                                    float(self.pos[2])))
            if np.isfinite(g) and self.pos[1] <= g:
                denom = float(prev[1] - self.pos[1])
                f = min(max((prev[1] - g) / denom, 0.0), 1.0) \
                    if denom > 1e-9 else 1.0
                self.pos = prev + (self.pos - prev) * f
                self.pos[1] = g
                events.append(("impact", self.pos.copy()))
                self.impacted = True
                self.done = True
                return
        if tf > self.twin_tof * 1.6 + 30.0:
            self.done = True               # lost-round guard

    def impact_fx(self, fx, pos) -> None:
        """Warhead-scaled ground burst: flash, frag dust sheet, rising
        column — sized by warhead_kg (24 kg 9M96 vs 180 kg 40N6)."""
        v = self.variant
        s = (v.warhead_kg / 145.0) ** (1.0 / 3.0)   # cube-root scaling
        r = fx.rng
        p = np.asarray(pos, dtype=np.float64) + np.array([0.0, 0.6, 0.0])
        w = _wind(fx, float(p[1]))
        fx.fire.emit(3, p, 0.8, (0.0, 0.0, 0.0), 0.0, (0.10, 0.18),
                     (9.0 * s, 15.0 * s),
                     ((1.0, 0.97, 0.85), (1.0, 0.8, 0.4)), r)
        fx.fire.emit(int(30 * s) + 6, p, 2.0 * s, (0.0, 10.0, 0.0), 8.0,
                     (0.25, 0.7), (1.2 * s, 4.5 * s),
                     ((1.0, 0.85, 0.5), (1.0, 0.45, 0.1)), r)
        idx = fx.smoke.emit(int(70 * s) + 10, p, 2.0 * s,
                            (0.0, 1.2, 0.0), 0.7, (2.5, 6.0),
                            (2.0 * s, 14.0 * s),
                            ((0.52, 0.47, 0.40), (0.42, 0.39, 0.35)), r,
                            alpha01=(0.8, 0.06), fade_in=0.04,
                            stretch=0.03)
        if len(idx):
            ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
            sp = r.uniform(26.0, 48.0, len(idx)) * s
            fx.smoke.vel[idx, 0] = (np.sin(ang) * sp).astype(np.float32)
            fx.smoke.vel[idx, 2] = (np.cos(ang) * sp).astype(np.float32)
            fx.smoke.vel[idx, 1] = r.uniform(1.0, 4.0, len(idx)) \
                .astype(np.float32)
        fx.smoke.emit(int(36 * s) + 8, p + np.array([0.0, 3.0, 0.0]),
                      3.5 * s, w + np.array([0.0, 5.0, 0.0]), 2.5,
                      (16.0, 36.0), (4.0 * s, 26.0 * s),
                      ((0.50, 0.46, 0.41), (0.40, 0.39, 0.37)), r,
                      alpha01=(0.6, 0.04), fade_in=0.10)


def next_variant(current_id: str, step: int = 1) -> MissileVariant:
    ids = [v.id for v in VARIANTS]
    i = (ids.index(current_id) + step) % len(ids) \
        if current_id in ids else 0
    return VARIANTS[i]
