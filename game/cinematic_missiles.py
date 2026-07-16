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
        ground_blast_mult=1.15, shake_amp=0.75),
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
        ground_blast_mult=1.25, shake_amp=0.60),
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
        ground_blast_mult=0.36, shake_amp=0.22),
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
        ground_blast_mult=2.30, shake_amp=1.10),
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


def next_variant(current_id: str, step: int = 1) -> MissileVariant:
    ids = [v.id for v in VARIANTS]
    i = (ids.index(current_id) + step) % len(ids) \
        if current_id in ids else 0
    return VARIANTS[i]
