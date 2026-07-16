"""Rolling terrain fog for cinematic scenes (GL-free sim).

Two fog populations, both driven by the scene's own data:

- HIGH FOG on the icy mountains: cells above the scene's snowline (the
  90th height percentile — the LiDAR peaks that actually hold snow)
  continuously breed slow fog banks in EVERY light mood.  Each bank
  drifts on the measured wind at its own altitude and RELAXES toward a
  hover height above the local ground, so when the flow pushes a bank
  across a ridge it climbs the windward side and pours down the lee —
  it rolls OVER the mountain instead of clipping through it (user
  request 2026-07-16).
- VALLEY FOG on the green floor: only in the grey-morning / golden-hour
  / night moods (radiation fog burns off under a high sun), with a
  gentle downslope drift so morning fog drains along the valley.

No hard terrain clipping: a bank's dense core is held above the ground
by its hover height and only the soft billboard skirt brushes the
surface, which reads as ground contact.  Everything is deterministic
per scene seed — same minute, same fog.

The sim owns a dedicated ``ParticlePool`` (``effects.fog``) that
``engine.particles.ParticleRenderer`` draws with the other alpha pools;
this module never touches GL.
"""

from __future__ import annotations

import numpy as np

from world.cinematic_shadows import compose_height_field

FOG_CAP = 2000               # dedicated pool capacity
FIELD_RES = 384              # coarse ground grid for steering/sources

# Steady-state bank counts (scaled per mood below).
HIGH_TARGET = 420
VALLEY_TARGET = 300

# Per-mood activity: (high-fog gain, valley-fog gain).  Valley radiation
# fog exists only when the sun is low or gone.
MOOD_GAIN = {
    "alpine": (0.65, 0.0),
    "noon":   (0.45, 0.0),
    "golden": (1.0, 0.8),
    "grey":   (1.30, 1.4),
    "night":  (1.0, 1.0),
}

BANK_LIFE = (70.0, 130.0)    # s
HIGH_COL = ((0.93, 0.95, 0.98), (0.86, 0.89, 0.93))
VALLEY_COL = ((0.84, 0.87, 0.90), (0.76, 0.80, 0.85))
WIND_FOLLOW = 0.55           # fog rides a bit slower than the free wind
RELAX_RATE = 0.22            # 1/s pull toward the hover height
MAX_POUR = 14.0              # m/s fastest lee-side descent
MAX_CLIMB = 6.0              # m/s fastest windward climb


class CinematicFog:
    """Terrain-hugging fog banks over one scene (see module docstring)."""

    def __init__(self, scene, pool, wind_profile=None, seed: int = 11):
        self.pool = pool
        self.wind = wind_profile
        self.rng = np.random.default_rng(seed)
        self.t = 0.0
        self.mood = "noon"
        # Coarse ground field: steering + gradient + source masks.
        field, x0, z0, cell = compose_height_field(scene,
                                                   max_res=FIELD_RES)
        self._f = field
        self._x0, self._z0, self._cell = x0, z0, cell
        valid = field > -9e3
        vals = field[valid]
        self.snow_y = float(np.percentile(vals, 90.0))
        self.floor_y = float(np.percentile(vals, 5.0))
        # Downslope direction (normalized negative gradient), for the
        # drainage drift of valley fog.
        gz, gx = np.gradient(field.astype(np.float64), cell)
        mag = np.hypot(gx, gz) + 1e-6
        self._down_x = (-gx / mag).astype(np.float32)
        self._down_z = (-gz / mag).astype(np.float32)
        # Source cells.
        jz, jx = np.nonzero(valid & (field >= self.snow_y))
        self._high_src = (x0 + jx * cell, z0 + jz * cell, field[jz, jx])
        low = valid & (field <= self.floor_y + 240.0)
        jz, jx = np.nonzero(low)
        self._val_src = (x0 + jx * cell, z0 + jz * cell, field[jz, jx])
        # Per-slot state (parallel to the pool arrays).
        cap = pool.cap
        self._hover = np.zeros(cap, dtype=np.float32)
        self._is_valley = np.zeros(cap, dtype=bool)
        self._phase = self.rng.uniform(0.0, 2.0 * np.pi, cap) \
            .astype(np.float32)
        self._carry_high = 0.0
        self._carry_val = 0.0

    # ----------------------------------------------------------- controls

    def set_mood(self, mood_id: str) -> None:
        if mood_id == self.mood:
            return
        self.mood = mood_id
        gain_high, gain_val = MOOD_GAIN.get(mood_id, (0.8, 0.0))
        if gain_val <= 0.0:
            # The sun climbed: existing valley fog burns off within ~20 s
            # instead of hanging into the wrong time of day.
            n = self.pool._hi
            sel = self._is_valley[:n] & self.pool.alive[:n]
            self.pool.life[:n][sel] = np.minimum(
                self.pool.life[:n][sel], self.rng.uniform(6.0, 20.0,
                                                          int(sel.sum()))
                .astype(np.float32))

    # ----------------------------------------------------------- sampling

    def _ground(self, xs, zs):
        """Vectorized bilinear ground height on the coarse field."""
        f = self._f
        gx = np.clip((xs - self._x0) / self._cell, 0.0, f.shape[1] - 1.001)
        gz = np.clip((zs - self._z0) / self._cell, 0.0, f.shape[0] - 1.001)
        i0 = gx.astype(np.int64)
        j0 = gz.astype(np.int64)
        fx = (gx - i0).astype(np.float32)
        fz = (gz - j0).astype(np.float32)
        return ((f[j0, i0] * (1 - fx) + f[j0, i0 + 1] * fx) * (1 - fz)
                + (f[j0 + 1, i0] * (1 - fx) + f[j0 + 1, i0 + 1] * fx) * fz)

    def _downslope(self, xs, zs):
        i = np.clip(np.round((xs - self._x0) / self._cell).astype(np.int64),
                    0, self._f.shape[1] - 1)
        j = np.clip(np.round((zs - self._z0) / self._cell).astype(np.int64),
                    0, self._f.shape[0] - 1)
        return self._down_x[j, i], self._down_z[j, i]

    # -------------------------------------------------------------- spawn

    def _spawn(self, src, count: int, valley: bool) -> None:
        xs, zs, hs = src
        if len(xs) == 0 or count <= 0:
            return
        idx = self.rng.integers(0, len(xs), count)
        jit = self._cell * 0.5
        col = VALLEY_COL if valley else HIGH_COL
        for k in idx:
            hover = float(self.rng.uniform(10.0, 42.0))
            pos = (float(xs[k] + self.rng.uniform(-jit, jit)),
                   float(hs[k] + hover),
                   float(zs[k] + self.rng.uniform(-jit, jit)))
            slots = self.pool.emit(
                1, pos, self._cell * 0.25, (0.0, 0.0, 0.0), 0.0,
                BANK_LIFE, (45.0, 115.0), col, self.rng,
                alpha01=(0.16, 0.0), fade_in=8.0)
            if len(slots):
                s = int(slots[0])
                self._hover[s] = hover
                self._is_valley[s] = valley

    # --------------------------------------------------------------- step

    def step(self, dt: float) -> None:
        """Advance the fog sim: breed banks toward the mood's targets,
        steer every live bank (wind + terrain-follow), integrate."""
        self.t += dt
        gain_high, gain_val = MOOD_GAIN.get(self.mood, (0.8, 0.0))
        mean_life = 0.5 * (BANK_LIFE[0] + BANK_LIFE[1])
        n = self.pool._hi
        alive = self.pool.alive[:n]
        n_val = int((alive & self._is_valley[:n]).sum())
        n_high = int(alive.sum()) - n_val
        self._carry_high += dt * max(
            0.0, (HIGH_TARGET * gain_high - n_high)) / mean_life * 2.5
        self._carry_val += dt * max(
            0.0, (VALLEY_TARGET * gain_val - n_val)) / mean_life * 2.5
        k = int(self._carry_high)
        self._carry_high -= k
        self._spawn(self._high_src, min(k, 8), valley=False)
        k = int(self._carry_val)
        self._carry_val -= k
        self._spawn(self._val_src, min(k, 8), valley=True)

        n = self.pool._hi
        if n:
            alive = self.pool.alive[:n]
            idx = np.flatnonzero(alive)
            if len(idx):
                pos = self.pool.pos[:n]
                xs = pos[idx, 0]
                ys = pos[idx, 1]
                zs = pos[idx, 2]
                if self.wind is not None:
                    w = self.wind.wind_field(ys, self.t) * WIND_FOLLOW
                else:
                    w = np.zeros((len(idx), 3), dtype=np.float32)
                    w[:, 0] = 1.2
                    w[:, 2] = 0.5
                # Slow per-bank churn so the layer doesn't slide as one
                # rigid sheet (deterministic per-slot phases).
                ph = self._phase[idx] + np.float32(self.t * 0.09)
                w[:, 0] += np.sin(ph) * 0.5
                w[:, 2] += np.cos(ph * 0.83) * 0.5
                # Valley drainage: down the local slope, strongest for
                # valley fog in the calm morning/night moods.
                if self.mood in ("grey", "night", "golden"):
                    dx, dz = self._downslope(xs, zs)
                    drain = np.where(self._is_valley[:n][idx], 0.9, 0.35) \
                        .astype(np.float32)
                    w[:, 0] += dx * drain
                    w[:, 2] += dz * drain
                # Terrain-follow: relax toward ground + hover.  The climb
                # is slow and the pour is faster — banks bulge over a
                # crest and cascade down the lee side.
                ground = self._ground(xs, zs)
                target = ground + self._hover[idx]
                vy = np.clip((target - ys) * RELAX_RATE,
                             -MAX_POUR, MAX_CLIMB).astype(np.float32)
                self.pool.vel[idx, 0] = w[:, 0]
                self.pool.vel[idx, 1] = vy
                self.pool.vel[idx, 2] = w[:, 2]
        # Ages + integrates with the velocities set above (drag 0 keeps
        # them exactly as steered).
        self.pool.update(dt, drag=0.0)
