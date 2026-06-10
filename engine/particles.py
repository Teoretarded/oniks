"""Vectorized particle pools + ribbon trails (numpy sim, GL draw split).

Sim side (``ParticlePool``, ``TrailRibbon``, ``Effects``) is pure numpy and
imported by unit tests. GL side (``ParticleRenderer``) defers every OpenGL
import to ``__init__`` (same pattern as ``world.ocean.Ocean``) so this module
stays importable headless (LOCKED test convention).

Precision (LOCKED): particle/trail positions are world-space ``np.float64``;
everything else is float32. ``build_quads``/``build_strip`` subtract the
camera eye in float64 and only then cast to float32 — the GPU never sees an
absolute world coordinate.

Vertex layout for both quads and ribbon strips, 10 float32 per vertex
(stride 40 bytes):

    [px py pz  u v  r g b a  size]

pos = camera-relative corner (billboard size already folded in), uv = soft
disc texture coordinate, rgba = tinted color + fade alpha, size = world
half-extent (spare channel, unused by the current shader).
"""

from __future__ import annotations

import numpy as np

from engine.shaderlib import HAZE_GLSL

# ---------------------------------------------------------------- tuning
# Trail ribbon (plan-fixed values)
TRAIL_POINT_SPACING = 35.0   # m of travel between stored ribbon points
TRAIL_MAX_POINTS = 1600      # ring-buffer capacity per ribbon
TRAIL_FADE_TIME = 22.0       # s before a ribbon point is fully transparent
TRAIL_WIDTH0 = 1.5           # m ribbon width at a fresh point
TRAIL_WIDTH1 = 14.0          # m ribbon width when fully aged (dispersed)
TRAIL_ALPHA = 0.55           # peak ribbon opacity (fresh point)
TRAIL_COL0 = np.array([0.97, 0.96, 0.94])   # fresh exhaust: near white
TRAIL_COL1 = np.array([0.72, 0.73, 0.76])   # aged: pale blue-gray

# Pool capacities (struct-of-arrays slots)
SMOKE_CAP = 6000             # alpha-blended smoke
FIRE_CAP = 3000              # additive fire / flash
SPRAY_CAP = 3000             # alpha-blended water spray (ballistic)

# Per-pool physics (passed to ParticlePool.update by Effects.update)
SMOKE_DRAG = 0.45            # 1/s exponential velocity decay
SMOKE_BUOYANCY = 1.7         # m/s^2 upward (hot smoke rises)
FIRE_DRAG = 1.8              # fire puffs stop fast
FIRE_BUOYANCY = 2.5          # m/s^2 upward
SPRAY_DRAG = 0.30
SPRAY_GRAVITY = 9.81         # m/s^2 down (spray falls back to the sea)

# Per-particle size variety multiplier sampled uniform in [LO, HI]
SIZE_JITTER_LO = 0.75
SIZE_JITTER_HI = 1.30

# Booster plume (emission per call; called once per sim step while thrusting)
PLUME_FIRE_COUNT = 3         # fire particles per call at full throttle
PLUME_SMOKE_COUNT = 2
PLUME_EXHAUST_SPEED = 55.0   # m/s backward ejection of plume particles

# Explosion (one-shot, counts scale with `scale`)
EXPL_FIREBALL_COUNT = 36
EXPL_SMOKE_COUNT = 60
EXPL_FIREBALL_SPEED = 26.0   # m/s radial scatter at scale=1
EXPL_SMOKE_RISE = 16.0       # m/s initial column rise at scale=1

# Splash (white spray ring + central column)
SPLASH_COUNT = 56
SPLASH_COLUMN_COUNT = 14
SPLASH_RING_SPEED = (14.0, 34.0)   # m/s horizontal radial speed range
SPLASH_RISE = 22.0                 # m/s mean upward kick of the ring
SPLASH_COLUMN_RISE = 30.0          # m/s upward speed of the central column

_UP = np.array([0.0, 1.0, 0.0])


def _as_range(x) -> tuple[float, float]:
    """Accept a scalar or a (lo, hi) pair; return (lo, hi)."""
    if np.isscalar(x):
        return float(x), float(x)
    return float(x[0]), float(x[1])


class ParticlePool:
    """Fixed-capacity struct-of-arrays particle pool (fully vectorized).

    Fields: pos (N,3) float64 world, vel (N,3) f32, life/max_life (N) f32,
    size0/size1 (N) f32, col0/col1 (N,3) f32, alive (N) bool.
    """

    def __init__(self, cap: int):
        self.cap = int(cap)
        n = self.cap
        self.pos = np.zeros((n, 3), dtype=np.float64)
        self.vel = np.zeros((n, 3), dtype=np.float32)
        self.life = np.zeros(n, dtype=np.float32)
        self.max_life = np.ones(n, dtype=np.float32)
        self.size0 = np.zeros(n, dtype=np.float32)
        self.size1 = np.zeros(n, dtype=np.float32)
        self.col0 = np.zeros((n, 3), dtype=np.float32)
        self.col1 = np.zeros((n, 3), dtype=np.float32)
        self.alive = np.zeros(n, dtype=bool)

    def emit(self, n, pos, pos_jitter, vel_mean, vel_jitter, life,
             size01, col01, rng) -> np.ndarray:
        """Spawn up to ``n`` particles (clamped to free slots).

        pos: (3,) world center; pos_jitter: gaussian sigma (scalar or per
        axis). vel_mean: (3,) m/s; vel_jitter: gaussian sigma. life: seconds,
        scalar or (lo, hi) sampled uniform. size01 = (birth, death) world
        size m; col01 = (birth_rgb, death_rgb). Returns the slot indices of
        the emitted particles (callers may post-shape e.g. splash rings).
        """
        free = np.flatnonzero(~self.alive)[:int(n)]
        k = len(free)
        if k == 0:
            return free
        center = np.asarray(pos, dtype=np.float64)
        self.pos[free] = center + rng.normal(0.0, pos_jitter, (k, 3))
        self.vel[free] = (np.asarray(vel_mean, dtype=np.float64)
                          + rng.normal(0.0, vel_jitter, (k, 3))
                          ).astype(np.float32)
        lo, hi = _as_range(life)
        lifes = rng.uniform(lo, hi, k).astype(np.float32) if hi > lo \
            else np.full(k, lo, dtype=np.float32)
        self.life[free] = lifes
        self.max_life[free] = np.maximum(lifes, np.float32(1e-6))
        scale = rng.uniform(SIZE_JITTER_LO, SIZE_JITTER_HI, k) \
            .astype(np.float32)
        self.size0[free] = np.float32(size01[0]) * scale
        self.size1[free] = np.float32(size01[1]) * scale
        self.col0[free] = np.asarray(col01[0], dtype=np.float32)
        self.col1[free] = np.asarray(col01[1], dtype=np.float32)
        self.alive[free] = True
        return free

    def update(self, dt, drag=0.15, gravity=0.0, buoyancy=0.0) -> None:
        """Vectorized step: age, kill life<=0, drag, vertical accel, move."""
        live = self.alive
        if not live.any():
            return
        self.life -= np.float32(dt)
        np.logical_and(live, self.life > 0.0, out=live)
        if drag:
            self.vel *= np.float32(np.exp(-drag * dt))
        acc = np.float32((buoyancy - gravity) * dt)
        if acc:
            self.vel[live, 1] += acc
        self.pos[live] += self.vel[live] * np.float32(dt)

    def build_quads(self, cam_eye, cam_right, cam_up) -> np.ndarray:
        """Camera-facing quads, back-to-front: (M*4, 10) float32.

        Per-vertex layout [px py pz u v r g b a size]; positions are
        camera-relative (float64 subtract, then float32 cast — LOCKED).
        """
        idx = np.flatnonzero(self.alive)
        m = len(idx)
        if m == 0:
            return np.empty((0, 10), dtype=np.float32)
        rel = (self.pos[idx]
               - np.asarray(cam_eye, dtype=np.float64)).astype(np.float32)
        # Sort back-to-front so alpha blending layers correctly.
        order = np.argsort(-np.einsum("ij,ij->i", rel, rel))
        idx = idx[order]
        rel = rel[order]

        frac = np.clip(1.0 - self.life[idx] / self.max_life[idx], 0.0, 1.0)
        half = 0.5 * (self.size0[idx] + (self.size1[idx] - self.size0[idx])
                      * frac)
        col = self.col0[idx] + (self.col1[idx] - self.col0[idx]) \
            * frac[:, None]
        alpha = 1.0 - frac

        right = np.asarray(cam_right, dtype=np.float32)
        up = np.asarray(cam_up, dtype=np.float32)
        out = np.empty((m, 4, 10), dtype=np.float32)
        h = half[:, None]
        for c, (ox, oy, u, v) in enumerate(((-1, -1, 0, 0), (1, -1, 1, 0),
                                            (1, 1, 1, 1), (-1, 1, 0, 1))):
            out[:, c, 0:3] = rel + (ox * h) * right + (oy * h) * up
            out[:, c, 3] = u
            out[:, c, 4] = v
        out[:, :, 5:8] = col[:, None, :]
        out[:, :, 8] = alpha[:, None]
        out[:, :, 9] = half[:, None] * 2.0
        return out.reshape(m * 4, 10)


class TrailRibbon:
    """Ring buffer of (pos float64, age) trail points behind a missile.

    A point is stored only after >= TRAIL_POINT_SPACING m of travel from the
    last stored point; capacity TRAIL_MAX_POINTS (oldest overwritten). Points
    fade out over TRAIL_FADE_TIME s and widen TRAIL_WIDTH0 -> TRAIL_WIDTH1.
    """

    def __init__(self):
        self._pos = np.zeros((TRAIL_MAX_POINTS, 3), dtype=np.float64)
        self._age = np.zeros(TRAIL_MAX_POINTS, dtype=np.float32)
        self._start = 0          # ring index of the oldest point
        self._count = 0
        self.finished = False    # set by the owner; empty+finished -> prune

    def __len__(self) -> int:
        return self._count

    def _indices(self) -> np.ndarray:
        """Ring indices ordered oldest -> newest."""
        return (self._start + np.arange(self._count)) % TRAIL_MAX_POINTS

    def add_point(self, pos) -> bool:
        """Store ``pos`` if it is >= TRAIL_POINT_SPACING from the last point."""
        p = np.asarray(pos, dtype=np.float64)
        if self._count:
            last = self._pos[(self._start + self._count - 1)
                             % TRAIL_MAX_POINTS]
            if np.linalg.norm(p - last) < TRAIL_POINT_SPACING:
                return False
        if self._count == TRAIL_MAX_POINTS:     # full: overwrite oldest
            w = self._start
            self._start = (self._start + 1) % TRAIL_MAX_POINTS
            self._count -= 1
        else:
            w = (self._start + self._count) % TRAIL_MAX_POINTS
        self._pos[w] = p
        self._age[w] = 0.0
        self._count += 1
        return True

    def update(self, dt) -> None:
        """Age all points; drop the (oldest-first) ones past the fade time."""
        if self._count == 0:
            return
        idx = self._indices()
        self._age[idx] += np.float32(dt)
        # Ages are monotonically decreasing oldest -> newest, so the expired
        # set is a prefix of the ring.
        n_dead = int((self._age[idx] > TRAIL_FADE_TIME).sum())
        self._start = (self._start + n_dead) % TRAIL_MAX_POINTS
        self._count -= n_dead

    def points(self) -> np.ndarray:
        """(P,3) float64 stored points, oldest -> newest."""
        return self._pos[self._indices()].copy()

    def build_strip(self, cam_eye) -> np.ndarray:
        """Camera-facing triangle-strip vertices: (P*2, 10) float32.

        Same per-vertex layout as ParticlePool.build_quads; left/right edge
        pairs per point, uv.x spanning the soft texture across the width.
        """
        if self._count < 2:
            return np.empty((0, 10), dtype=np.float32)
        idx = self._indices()
        pts = self._pos[idx]                       # (P,3) f64
        ages = self._age[idx].astype(np.float64)
        rel = pts - np.asarray(cam_eye, dtype=np.float64)

        tangent = np.empty_like(pts)
        tangent[1:-1] = pts[2:] - pts[:-2]
        tangent[0] = pts[1] - pts[0]
        tangent[-1] = pts[-1] - pts[-2]
        side = np.cross(tangent, rel)              # camera-facing ribbon
        norm = np.linalg.norm(side, axis=1)
        bad = norm < 1e-9
        side[bad] = (1.0, 0.0, 0.0)
        side /= np.where(bad, 1.0, norm)[:, None]

        frac = np.clip(ages / TRAIL_FADE_TIME, 0.0, 1.0)
        half = 0.5 * (TRAIL_WIDTH0 + (TRAIL_WIDTH1 - TRAIL_WIDTH0) * frac)
        alpha = TRAIL_ALPHA * (1.0 - frac)
        col = TRAIL_COL0 + (TRAIL_COL1 - TRAIL_COL0) * frac[:, None]

        p = len(pts)
        out = np.empty((p, 2, 10), dtype=np.float32)
        off = side * half[:, None]
        out[:, 0, 0:3] = rel - off
        out[:, 1, 0:3] = rel + off
        out[:, 0, 3] = 0.0
        out[:, 1, 3] = 1.0
        out[:, :, 4] = 0.5             # sample across the soft disc's middle
        out[:, :, 5:8] = col[:, None, :]
        out[:, :, 8] = alpha[:, None]
        out[:, :, 9] = (half * 2.0)[:, None]
        return out.reshape(p * 2, 10)


class Effects:
    """Owns the particle pools, trail ribbons and the effects RNG.

    Pools: ``smoke`` + ``spray`` draw alpha-blended, ``fire`` draws additive
    (spray is a separate pool only because it needs gravity instead of
    buoyancy — visually it belongs to the alpha group).
    """

    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng(seed)
        self.smoke = ParticlePool(SMOKE_CAP)
        self.fire = ParticlePool(FIRE_CAP)
        self.spray = ParticlePool(SPRAY_CAP)
        self.trails: list[TrailRibbon] = []

    def add_trail(self) -> TrailRibbon:
        """Create and register a ribbon; the caller feeds it points."""
        trail = TrailRibbon()
        self.trails.append(trail)
        return trail

    def update(self, dt) -> None:
        """Advance all pools with their physics; age + prune trails."""
        self.smoke.update(dt, drag=SMOKE_DRAG, buoyancy=SMOKE_BUOYANCY)
        self.fire.update(dt, drag=FIRE_DRAG, buoyancy=FIRE_BUOYANCY)
        self.spray.update(dt, drag=SPRAY_DRAG, gravity=SPRAY_GRAVITY)
        for trail in self.trails:
            trail.update(dt)
        self.trails = [t for t in self.trails
                       if not (t.finished and len(t) == 0)]

    # ------------------------------------------------------ spawn helpers

    def booster_plume(self, pos, direction, throttle, rng=None) -> None:
        """Per-frame exhaust emission while thrusting (dir = missile fwd)."""
        if throttle <= 0.0:
            return
        r = self.rng if rng is None else rng
        d = np.asarray(direction, dtype=np.float64)
        d = d / max(np.linalg.norm(d), 1e-9)
        back = -d * (PLUME_EXHAUST_SPEED * float(throttle))
        n_fire = max(1, int(round(PLUME_FIRE_COUNT * throttle)))
        self.fire.emit(n_fire, pos, 0.7, back, 6.0, (0.12, 0.3),
                       (1.3, 3.6), ((1.0, 0.86, 0.45), (1.0, 0.35, 0.08)), r)
        n_smoke = max(1, int(round(PLUME_SMOKE_COUNT * throttle)))
        self.smoke.emit(n_smoke, pos, 1.0, back * 0.45, 4.0, (1.2, 2.4),
                        (1.6, 7.5),
                        ((0.78, 0.76, 0.73), (0.50, 0.50, 0.53)), r)

    def explosion(self, pos, scale, rng=None, water=False) -> None:
        """One-shot blast: flash + fireball + smoke column (+ spray ring)."""
        r = self.rng if rng is None else rng
        s = float(scale)
        # Flash: two huge, very short additive sprites.
        self.fire.emit(2, pos, 0.5 * s, (0.0, 0.0, 0.0), 0.0, 0.12,
                       (16.0 * s, 30.0 * s),
                       ((1.0, 0.97, 0.85), (1.0, 0.6, 0.2)), r)
        # Fireball: radial additive scatter.
        self.fire.emit(max(12, int(EXPL_FIREBALL_COUNT * s)), pos, 2.5 * s,
                       (0.0, 9.0 * s, 0.0), EXPL_FIREBALL_SPEED * s,
                       (0.4, 1.0), (5.0 * s, 16.0 * s),
                       ((1.0, 0.78, 0.32), (0.75, 0.18, 0.03)), r)
        # Smoke column: dark, slow, rises on pool buoyancy.
        self.smoke.emit(max(16, int(EXPL_SMOKE_COUNT * s)), pos, 4.0 * s,
                        (0.0, EXPL_SMOKE_RISE * s, 0.0), 6.0 * s,
                        (3.5, 8.0), (8.0 * s, 34.0 * s),
                        ((0.16, 0.15, 0.14), (0.42, 0.42, 0.44)), r)
        if water:
            self.splash(pos, rng=r, scale=s)

    def splash(self, pos, rng=None, scale=1.0) -> None:
        """White spray: radial ring + tall central column, gravity-ballistic."""
        r = self.rng if rng is None else rng
        s = float(scale)
        spray_col = ((0.93, 0.96, 1.0), (0.72, 0.78, 0.85))
        idx = self.spray.emit(int(SPLASH_COUNT * s), pos, 1.5,
                              (0.0, SPLASH_RISE, 0.0), 4.0, (1.2, 2.2),
                              (2.2 * s, 7.5 * s), spray_col, r)
        if len(idx):
            # Re-shape horizontal velocity into an outward ring.
            ang = r.uniform(0.0, 2.0 * np.pi, len(idx))
            speed = r.uniform(SPLASH_RING_SPEED[0], SPLASH_RING_SPEED[1],
                              len(idx)) * s
            self.spray.vel[idx, 0] = (np.sin(ang) * speed).astype(np.float32)
            self.spray.vel[idx, 2] = (np.cos(ang) * speed).astype(np.float32)
        self.spray.emit(int(SPLASH_COLUMN_COUNT * s), pos, 1.0,
                        (0.0, SPLASH_COLUMN_RISE * s, 0.0), 3.5, (1.4, 2.4),
                        (3.0 * s, 9.0 * s), spray_col, r)

    def ship_fire(self, pos, rng=None) -> None:
        """Per-frame deck fire + black smoke while a ship burns/sinks."""
        r = self.rng if rng is None else rng
        self.fire.emit(2, pos, 3.0, (0.0, 5.0, 0.0), 1.5, (0.35, 0.8),
                       (2.5, 6.0), ((1.0, 0.72, 0.28), (0.85, 0.2, 0.04)), r)
        self.smoke.emit(1, pos + _UP * 4.0, 2.5, (0.0, 6.5, 0.0), 2.0,
                        (2.5, 6.0), (3.5, 16.0),
                        ((0.07, 0.07, 0.07), (0.22, 0.22, 0.24)), r)


# ---------------------------------------------------------------- GL side

PARTICLE_VERT = """
#version 330 core
layout(location=0) in vec3 a_pos;   // camera-relative, size folded in
layout(location=1) in vec2 a_uv;
layout(location=2) in vec4 a_col;
uniform mat4 u_proj, u_view_rot;
uniform float u_log_depth_fcoef;
out vec2 v_uv; out vec4 v_col; out vec3 v_view_vec;
void main(){
    v_uv = a_uv; v_col = a_col; v_view_vec = a_pos;
    gl_Position = u_proj * u_view_rot * vec4(a_pos, 1.0);
    gl_Position.z = (log2(max(1e-6, 1.0 + gl_Position.w)) * u_log_depth_fcoef - 1.0) * gl_Position.w;
}
"""

PARTICLE_FRAG = """
#version 330 core
in vec2 v_uv; in vec4 v_col; in vec3 v_view_vec;
uniform sampler2D u_tex;
uniform int u_additive;
out vec4 frag;
""" + HAZE_GLSL + """
void main(){
    float a = texture(u_tex, v_uv).r * v_col.a;
    if (a < 0.004) discard;
    vec3 col = v_col.rgb;
    if (u_additive == 1) {
        // Additive sprites must not scatter haze color in: attenuate only.
        float h = max(u_cam_alt + v_view_vec.y * 0.5, 0.0);
        float density = u_haze_density * exp(-h / 6000.0);
        col *= exp(-density * length(v_view_vec));
    } else {
        col = apply_haze(col, v_view_vec, u_cam_alt);
    }
    frag = vec4(col, a);
}
"""

_STRIDE = 40        # 10 floats * 4 bytes
_TEX_SIZE = 64      # soft-disc texture resolution
_DISC_INNER = 0.35  # smoothstep start radius of the soft disc


def build_soft_disc(size: int = _TEX_SIZE) -> np.ndarray:
    """(size, size) uint8 soft disc: 1 - smoothstep(0.35, 1.0, r). GL-free."""
    c = (np.arange(size) + 0.5) / size * 2.0 - 1.0      # texel centers
    xx, yy = np.meshgrid(c, c)
    r = np.sqrt(xx * xx + yy * yy)
    t = np.clip((r - _DISC_INNER) / (1.0 - _DISC_INNER), 0.0, 1.0)
    disc = 1.0 - t * t * (3.0 - 2.0 * t)
    return np.round(disc * 255.0).astype(np.uint8)


class ParticleRenderer:
    """Streamed-VBO billboard/ribbon renderer (GL-touching; never in tests)."""

    def __init__(self):
        import ctypes
        import OpenGL.GL as gl
        from engine.shader import Shader
        self._gl = gl
        self.shader = Shader(PARTICLE_VERT, PARTICLE_FRAG)

        # Procedural soft-disc texture (single red channel).
        disc = build_soft_disc()
        self.tex = gl.glGenTextures(1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, gl.GL_R8, _TEX_SIZE, _TEX_SIZE,
                        0, gl.GL_RED, gl.GL_UNSIGNED_BYTE, disc)
        for pname, val in ((gl.GL_TEXTURE_MIN_FILTER, gl.GL_LINEAR),
                           (gl.GL_TEXTURE_MAG_FILTER, gl.GL_LINEAR),
                           (gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE),
                           (gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)):
            gl.glTexParameteri(gl.GL_TEXTURE_2D, pname, val)

        # Quad path: streamed VBO + one static EBO covering the biggest pool.
        max_quads = max(SMOKE_CAP, FIRE_CAP, SPRAY_CAP)
        base = np.arange(max_quads, dtype=np.uint32) * 4
        ebo_idx = np.stack([base, base + 1, base + 2,
                            base, base + 2, base + 3], axis=1).ravel()
        self.quad_vao, self.quad_vbo = self._make_vao(ctypes)
        self.quad_ebo = gl.glGenBuffers(1)
        gl.glBindVertexArray(self.quad_vao)
        gl.glBindBuffer(gl.GL_ELEMENT_ARRAY_BUFFER, self.quad_ebo)
        gl.glBufferData(gl.GL_ELEMENT_ARRAY_BUFFER, ebo_idx.nbytes, ebo_idx,
                        gl.GL_STATIC_DRAW)
        gl.glBindVertexArray(0)

        # Ribbon path: streamed VBO drawn as GL_TRIANGLE_STRIP.
        self.strip_vao, self.strip_vbo = self._make_vao(ctypes)

    def _make_vao(self, ctypes):
        """VAO + streamed VBO with the 10-float vertex layout bound."""
        gl = self._gl
        vao = gl.glGenVertexArrays(1)
        vbo = gl.glGenBuffers(1)
        gl.glBindVertexArray(vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
        for loc, n, offset in ((0, 3, 0), (1, 2, 12), (2, 4, 20)):
            gl.glVertexAttribPointer(loc, n, gl.GL_FLOAT, gl.GL_FALSE,
                                     _STRIDE, ctypes.c_void_p(offset))
            gl.glEnableVertexAttribArray(loc)
        gl.glBindVertexArray(0)
        return vao, vbo

    def draw(self, renderer, effects: Effects) -> None:
        """Draw all effects: smoke/spray/trails alpha, fire additive.

        Call after all opaque geometry; depth test stays on but depth writes
        are off so particles never punch holes in each other.
        """
        gl = self._gl
        cam = renderer.camera
        eye, right, up = cam.eye, cam.right, cam.up
        smoke = effects.smoke.build_quads(eye, right, up)
        spray = effects.spray.build_quads(eye, right, up)
        fire = effects.fire.build_quads(eye, right, up)
        strips = [t.build_strip(eye) for t in effects.trails]
        strips = [s for s in strips if len(s)]
        if not (len(smoke) or len(spray) or len(fire) or strips):
            return

        renderer.set_common(self.shader)     # binds shader + frame uniforms
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.tex)
        self.shader.set_int("u_tex", 0)
        gl.glEnable(gl.GL_BLEND)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDisable(gl.GL_CULL_FACE)        # billboards have no back side

        self.shader.set_int("u_additive", 0)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        for strip in strips:
            self._draw_strip(strip)
        self._draw_quads(smoke)
        self._draw_quads(spray)

        self.shader.set_int("u_additive", 1)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE)
        self._draw_quads(fire)

        gl.glEnable(gl.GL_CULL_FACE)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)

    def _draw_quads(self, data: np.ndarray) -> None:
        if len(data) == 0:
            return
        gl = self._gl
        gl.glBindVertexArray(self.quad_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.quad_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data,
                        gl.GL_STREAM_DRAW)
        gl.glDrawElements(gl.GL_TRIANGLES, (len(data) // 4) * 6,
                          gl.GL_UNSIGNED_INT, None)
        gl.glBindVertexArray(0)

    def _draw_strip(self, data: np.ndarray) -> None:
        if len(data) < 4:
            return
        gl = self._gl
        gl.glBindVertexArray(self.strip_vao)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.strip_vbo)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, data.nbytes, data,
                        gl.GL_STREAM_DRAW)
        gl.glDrawArrays(gl.GL_TRIANGLE_STRIP, 0, len(data))
        gl.glBindVertexArray(0)

    def delete(self) -> None:
        gl = self._gl
        if self.quad_vao:
            gl.glDeleteVertexArrays(2, [self.quad_vao, self.strip_vao])
            gl.glDeleteBuffers(3, [self.quad_vbo, self.quad_ebo,
                                   self.strip_vbo])
            gl.glDeleteTextures(1, [self.tex])
            self.quad_vao = self.strip_vao = 0
            self.quad_vbo = self.quad_ebo = self.strip_vbo = 0
            self.tex = 0
