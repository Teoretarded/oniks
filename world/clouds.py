"""Volumetric clouds (F3-P4; spec: weather_system_design_2026-07-07.md
PART 2 §12 + the locked F3 conventions).

TWO HALVES, one module:

* The BAKE half (this top section) is pure NumPy — importable by unit
  tests and, in W-P6, by ``sim/atmosphere.py`` (the CPU/GPU single-source
  contract: the density the sim queries IS the density the GPU draws).
  Seeded ``default_rng([seed, 17])`` (tag 17 — the F3-reserved stream).
  Every field is PERIODIC so the GPU textures REPEAT seamlessly.

* The GL half (``Clouds``) defers every GL import to ``__init__``
  (sky.py pattern; never imported by unit tests): uploads the baked
  textures, draws one fullscreen raymarch pass after opaque geometry and
  before particles into the default framebuffer — depth TEST on
  (terrain/ships occlude clouds via the
  slab-entry log depth), depth WRITE off, premultiplied blend,
  ``apply_haze`` on the result.  Animation clock = SIM time (replays
  identical), never wall clock.

Determinism guard (LOCKED): no sim module imports this file
(tests/test_cloud_bake.py greps for offenders).

GPU density anti-wallpaper formulas (W-P6 must mirror these on CPU):
* Base lookup domain warp samples ``weather`` at
  ``wp.xz / (WEATHER_TILE_M * 0.37) + 0.618`` and uses
  ``(gb - 0.5) * 5000 m`` as an x/z offset, applied only to base noise.
* Two-scale base samples ``base`` at the warped ``(wp + drift)`` position
  over ``BASE_TILE_M`` and ``BASE_TILE_M * 2.618``, then blends
  ``base = mix(b1, b2, 0.38)`` before the density remap.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

# --- bake constants -------------------------------------------------------------
BASE_N = 128          # base Perlin-Worley texture, voxels per axis
DETAIL_N = 32         # detail Worley texture
WEATHER_N = 512       # weathermap texels per axis
CACHE_VERSION = "v6"  # bump when the bake recipe changes (invalidates caches)

# World-space scales (metres) — consumed by the shader AND (W-P6) the CPU
# density query, so they live here as the single source of truth.
CLOUD_BASE_M = 800.0        # slab bottom (fair-cu base band; 300 m read
                            # as fog height — playtest 2026-07-07)
CLOUD_TOP_M = 14_000.0      # slab top (supercell ceiling)
WEATHER_TILE_M = 300_000.0  # weathermap repeat period
BASE_TILE_M = 6_000.0       # base-noise repeat period
DETAIL_TILE_M = 1_200.0     # detail-noise repeat period


# --- periodic value noise (vectorized, float32) ---------------------------------

def _fade(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def _perlin_grid(rng, freq: int, dims: int) -> np.ndarray:
    """Periodic unit-gradient lattice, (freq,)*dims + (dims,) float32."""
    g = rng.standard_normal((freq,) * dims + (dims,)).astype(np.float32)
    g /= np.linalg.norm(g, axis=-1, keepdims=True) + 1e-9
    return g


def _perlin3(rng, n: int, freq: int) -> np.ndarray:
    """Periodic 3D Perlin, (n, n, n) float32 roughly in [-1, 1].  Fully
    vectorized: 8 corner gathers of (n,n,n,3) float32 (~25 MB each at
    128³, transient) — the slice-looped version measured 15+ s, this is
    sub-second."""
    g = _perlin_grid(rng, freq, 3)
    c = np.arange(n, dtype=np.float32) * (freq / n)
    i0 = c.astype(np.int64) % freq
    i1 = (i0 + 1) % freq
    f = (c - np.floor(c)).astype(np.float32)
    u = _fade(f)
    ax = (slice(None), None, None)
    ay = (None, slice(None), None)
    az = (None, None, slice(None))
    acc = None
    for xi, wx, dx in ((i0, 1.0 - u, f), (i1, u, f - 1.0)):
        for yi, wy, dy in ((i0, 1.0 - u, f), (i1, u, f - 1.0)):
            for zi, wz, dz in ((i0, 1.0 - u, f), (i1, u, f - 1.0)):
                gv = g[xi[:, None, None], yi[None, :, None],
                       zi[None, None, :]]              # (n, n, n, 3)
                d = (gv[..., 0] * dx[ax] + gv[..., 1] * dy[ay]
                     + gv[..., 2] * dz[az])
                w = wx[ax] * wy[ay] * wz[az]
                acc = d * w if acc is None else acc + d * w
    return acc


def _perlin2(rng, n: int, freq: int) -> np.ndarray:
    """Periodic 2D Perlin, (n, n) float32 roughly in [-1, 1]."""
    g = _perlin_grid(rng, freq, 2)
    c = np.arange(n, dtype=np.float32) * (freq / n)
    i0 = c.astype(np.int64) % freq
    i1 = (i0 + 1) % freq
    f = (c - np.floor(c)).astype(np.float32)
    u = _fade(f)
    acc = np.zeros((n, n), dtype=np.float32)
    for xi, wx, dx in ((i0, 1.0 - u[:, None], f[:, None]),
                       (i1, u[:, None], f[:, None] - 1.0)):
        for yi, wy, dy in ((i0, 1.0 - u[None, :], f[None, :]),
                           (i1, u[None, :], f[None, :] - 1.0)):
            gv = g[xi[:, None], yi[None, :]]               # (n, n, 2)
            acc += (gv[..., 0] * dx + gv[..., 1] * dy) * (wx * wy)
    return acc


def _fbm(noise_fn, rng, n: int, freq0: int, octaves: int) -> np.ndarray:
    """Normalized fbm in [0, 1]."""
    total = None
    amp, freq, norm = 1.0, freq0, 0.0
    for _ in range(octaves):
        layer = noise_fn(rng, n, freq) * amp
        total = layer if total is None else total + layer
        norm += amp
        amp *= 0.5
        freq *= 2
    total /= norm
    return np.clip(total * 0.5 + 0.5, 0.0, 1.0).astype(np.float32)


def _worley(rng, n: int, cells: int, dims: int) -> np.ndarray:
    """Periodic inverted Worley in [0, 1] (1 at feature points, 0 far),
    (n,)*dims float32.  Block-wise: the volume reshapes into per-cell
    blocks so each of the 3^dims neighbor offsets is ONE broadcast over
    (cells^dims, block^dims) with a tiny per-CELL feature gather — the
    per-pixel-gather version measured ~7 s per 128³ octave; this is
    sub-second."""
    assert n % cells == 0
    bs = n // cells
    pts = rng.random((cells,) * dims + (dims,)).astype(np.float32)
    pts_flat = pts.reshape(-1, dims)                      # (C, dims)
    # Block-local pixel coords in CELL units, shared by every cell:
    local_1d = (np.arange(bs, dtype=np.float32) + 0.5) / bs   # (bs,)
    local = np.stack(np.meshgrid(*([local_1d] * dims), indexing="ij"),
                     axis=-1).reshape(1, -1, dims)        # (1, bs^d, dims)
    cell_idx_1d = np.arange(cells)
    cell_grid = np.stack(np.meshgrid(*([cell_idx_1d] * dims),
                                     indexing="ij"),
                         axis=-1).reshape(-1, dims)       # (C, dims)
    best = np.full((cells ** dims, bs ** dims), np.inf, dtype=np.float32)
    offsets = np.stack(np.meshgrid(*([(-1, 0, 1)] * dims),
                                   indexing="ij"), -1).reshape(-1, dims)
    strides = np.array([cells ** (dims - 1 - d) for d in range(dims)])
    for off in offsets:
        nb = (cell_grid + off) % cells                    # (C, dims)
        nb_flat = nb @ strides                            # (C,)
        # Feature point position RELATIVE to each cell's own origin:
        p_rel = (pts_flat[nb_flat] + off).astype(np.float32)[:, None, :]
        delta = local - p_rel                             # (C, bs^d, dims)
        d2 = np.einsum("cpd,cpd->cp", delta, delta)
        np.minimum(best, d2, out=best)
    # Un-blockify: (cells, cells, cells, bs, bs, bs) -> interleaved axes.
    vol = best.reshape((cells,) * dims + (bs,) * dims)
    order = []
    for d in range(dims):
        order += [d, dims + d]
    dist = np.sqrt(vol.transpose(order).reshape((n,) * dims))
    dist /= np.sqrt(dims)                                 # ~[0, 1]
    return np.clip(1.0 - dist * 1.6, 0.0, 1.0).astype(np.float32)


def _remap(x, a, b, c, d):
    return c + (x - a) / np.maximum(b - a, 1e-6) * (d - c)


# --- the bake --------------------------------------------------------------------

def build_noise(seed: int, cache_dir=Path("cache")) -> dict:
    """The three cloud fields, seeded ``default_rng([seed, 17])`` (tag 17):

    * ``base``    (128³): Perlin-Worley — fbm Perlin remapped by Worley
      billows (Schneider/Nubis recipe) — the cloud SHAPES.
    * ``detail``  (32³): Worley — edge erosion.
    * ``weather`` (512²×3): R coverage / G type / B top-height fraction —
      WHERE clouds are and WHAT KIND (PART 2 §12; v1 bakes the FAIR/PARTLY
      mix, preset knobs arrive with W-P6).  All periodic.

    ``cache_dir`` None disables the disk cache (tests); otherwise
    ``cache/clouds_{CACHE_VERSION}_seed{seed}.npz`` makes the bake one-time
    per seed.
    """
    cache = None
    if cache_dir is not None:
        cache = Path(cache_dir) / f"clouds_{CACHE_VERSION}_seed{seed}.npz"
        if cache.exists():
            z = np.load(cache)
            return {"base": z["base"], "detail": z["detail"],
                    "weather": z["weather"]}

    rng = np.random.default_rng([int(seed), 17])

    # Base: fbm Perlin carved by Worley billows.  The raw fbm sits in a
    # compressed ~[0.3, 0.7] band — stretch to full range first so the
    # shader's coverage threshold has real contrast to bite on.
    perlin = _fbm(_perlin3, rng, BASE_N, 4, 3)
    perlin = np.clip(_remap(perlin, 0.30, 0.70, 0.0, 1.0), 0.0, 1.0)
    worley = (_worley(rng, BASE_N, 4, 3) * 0.625
              + _worley(rng, BASE_N, 8, 3) * 0.25
              + _worley(rng, BASE_N, 16, 3) * 0.125)
    base = np.clip(_remap(perlin, worley - 1.0, 1.0, 0.0, 1.0),
                   0.0, 1.0).astype(np.float32)

    # Detail: three Worley octaves, erodes cloud edges in the shader.
    detail = (_worley(rng, DETAIL_N, 2, 3) * 0.5
              + _worley(rng, DETAIL_N, 4, 3) * 0.3
              + _worley(rng, DETAIL_N, 8, 3) * 0.2).astype(np.float32)

    # Weathermap: coverage / type / top-height (FAIR/PARTLY default mix).
    # TWO-SCALE coverage (v6, playtest 2026-07-07 "zero variation"):
    # large weather MASSES (freq 3 — tens of km) modulate a small PUFF
    # field (freq 9) — clusters, lone puffs and honest clear lanes emerge
    # instead of one same-size blob wallpaper.
    mass_n = _fbm(_perlin2, rng, WEATHER_N, 3, 3)
    puff_n = _fbm(_perlin2, rng, WEATHER_N, 9, 3)
    mass = np.clip(_remap(mass_n, 0.50, 0.70, 0.0, 1.0), 0.0, 1.0)
    puff = np.clip(_remap(puff_n, 0.44, 0.62, 0.0, 1.0), 0.0, 1.0)
    lone = (0.55 * np.clip(_remap(puff_n, 0.68, 0.80, 0.0, 1.0), 0.0, 1.0)
            * (1.0 - mass))
    # Probed 2026-07-07 across seeds 7/0/1337: clear(<0.1) 0.6866-0.7291,
    # dense(>0.4) 0.0905-0.0964 — FAIR ~3 okta with lone puffs intact.
    coverage = np.clip(mass * (0.30 + 1.00 * puff) + 0.40 * mass * mass
                       + lone, 0.0, 1.0)
    type_n = _fbm(_perlin2, rng, WEATHER_N, 3, 2)      # low-freq type bands
    top_n = _fbm(_perlin2, rng, WEATHER_N, 4, 3)
    # Type channel (PART 2 §12): fair cumulus baseline, TALLER/denser
    # cores inside the mass centers (towering-cu patches); stratus/
    # supercell/cirrus arrive with the W-P6 preset knobs.
    ctype = np.clip(0.25 + 0.35 * mass + 0.15 * type_n, 0.0, 0.7)
    # Column tops vary with the mass (big systems build higher).
    top = np.clip(0.16 + 0.55 * mass * (0.5 + top_n) + 0.10 * top_n,
                  0.10, 1.0)
    weather = np.stack([coverage, ctype, top], axis=-1).astype(np.float32)

    out = {"base": base, "detail": detail, "weather": weather}
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(cache, **out)
    return out


# =================================================================== GL half
# Deferred-GL from here down (sky.py pattern): unit tests import the bake
# above; only the game render path constructs ``Clouds``.

CLOUD_VERT = """
#version 330 core
layout(location=0) in vec2 a_pos;          // fullscreen triangle, NDC
out vec2 v_ndc;
void main(){
    v_ndc = a_pos;
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
"""

# The raymarcher (locked F3 conventions + PART 2 §12 taxonomy):
#  * slab [u_cloud_base, u_cloud_top], march <= MARCH_STEPS with early-out,
#    march distance capped, dithered start offset (screen-space hash);
#  * density = base Perlin-Worley remapped by weathermap coverage, shaped
#    by a per-type vertical profile, eroded by detail Worley;
#  * lighting = Beer-Lambert x powder x dual-lobe-ish HG, 4-step sun cone,
#    ambient from the sky gradient pair;
#  * depth: gl_FragDepth at the SLAB ENTRY point via the exact locked
#    log-depth formula log2(1 + w) * fcoef * 0.5 (terrain occludes);
#  * apply_haze() on the lit result; premultiplied-alpha output.
CLOUD_FRAG = """
#version 330 core
in vec2 v_ndc;
uniform mat4 u_inv_proj_rot;      // inverse(proj * view_rot): NDC -> ray
uniform mat4 u_proj, u_view_rot;  // forward path for the entry-point depth
uniform vec3 u_cam_pos;           // world-space camera (noise sampling)
uniform float u_time;             // SIM time (replay-identical drift)
uniform float u_cloud_base, u_cloud_top;
uniform float u_coverage_bias;    // W-P8 preset knob (0 = baked map as-is)
uniform float u_log_depth_fcoef;
uniform sampler3D u_base_noise;
uniform sampler3D u_detail_noise;
uniform sampler2D u_weather;
uniform vec3 u_sun_color;
out vec4 frag;
""" + "__HAZE__" + """

const int   MARCH_STEPS   = 224;   // single march; v6 saves sun taps instead
const int   SUN_STEPS     = 4;
const float DT_MIN_M      = 60.0;     // near-field step
const float DT_MAX_M      = 6000.0;   // far-field stride with mip'd noise
const float DY_MAX_M      = 250.0;    // no >250 m vertical slice per sample
const float MARCH_DIST_CAP = 450000.0;
const float SUN_STEP_M    = 350.0;
const float SUN_COARSE_EXTRA_M = 1800.0;
const float SUN_COARSE_DIST_M = SUN_STEP_M * float(SUN_STEPS + 1)
                                + SUN_COARSE_EXTRA_M;
const float SUN_COARSE_WEIGHT_M = 1800.0;
const float SIGMA         = 0.016;    // extinction per density per metre
                                      // (0.022 stippled: speckle amplitude
                                      // tracks sigma*d*dt per step)
const float WEATHER_TILE  = 300000.0;
const float BASE_TILE     = 6000.0;
const float DETAIL_TILE   = 1200.0;
const float WIND_MS       = 18.0;     // slab drift, sim-time clocked
const float BASE_RATIO    = 2.618;
const float BASE_BLEND    = 0.38;
const float WARP_WEATHER_SCALE = 0.37;
const float WARP_OFFSET_M = 5000.0;
const float DETAIL_FADE0_M = 8000.0;
const float DETAIL_FADE1_M = 25000.0;
const float FAR_FLAT0_M    = 120000.0;
const float FAR_FLAT1_M    = 400000.0;

float remap(float x, float a, float b, float c, float d){
    return c + (x - a) / max(b - a, 1e-5) * (d - c);
}

float march_dt(float t, vec3 rd, float skip_mul){
    // 3% growth: 224 steps reach 450+ km while 10 km out still steps
    // ~300 m (0.055 stepped ~550 m there and stippled - v5 gate).
    float dt_prop = clamp(t * 0.03, DT_MIN_M, DT_MAX_M) * skip_mul;
    float dt_dy = DY_MAX_M / max(abs(rd.y), 0.02);
    return min(dt_prop, dt_dy);
}

// Per-type vertical profile (PART 2 §12): type 0 stratus (thin, low flat),
// 0.25 fair cu, 0.5 towering, 0.75 cumulonimbus, 1.0 cirrus (thin, high).
float height_profile(float hfrac, float ctype, float top){
    float h = hfrac / max(top, 0.05);          // 0..1 inside THIS column
    if (h > 1.0) return 0.0;
    float bottom = smoothstep(0.0, 0.08 + 0.12 * ctype, h);
    float cap    = 1.0 - smoothstep(0.6 + 0.35 * ctype, 1.0, h);
    // Cirrus band: thin sheet riding near the column top.
    float cirrus = smoothstep(0.75, 0.9, h) * (1.0 - smoothstep(0.9, 1.0, h));
    return mix(bottom * cap, cirrus * 0.35, step(0.9, ctype));
}

float density_at(vec3 wp, float view_t){
    float hfrac = (wp.y - u_cloud_base) / (u_cloud_top - u_cloud_base);
    if (hfrac < 0.0 || hfrac > 1.0) return 0.0;
    vec3 drift = vec3(u_time * WIND_MS, 0.0, u_time * WIND_MS * 0.35);
    vec2 wuv = (wp.xz + drift.xz) / WEATHER_TILE;
    vec3 wm = texture(u_weather, wuv).rgb;     // coverage, type, top
    float coverage = clamp(wm.r + u_coverage_bias, 0.0, 1.0);
    if (coverage <= 0.01) return 0.0;
    float prof = height_profile(hfrac, wm.g, max(wm.b, 0.12));
    if (prof <= 0.0) return 0.0;
    float far_flat = smoothstep(FAR_FLAT0_M, FAR_FLAT1_M, view_t) * 0.6;
    vec2 warp_uv = wp.xz / (WEATHER_TILE * WARP_WEATHER_SCALE) + vec2(0.618);
    vec2 base_warp = (texture(u_weather, warp_uv).gb - vec2(0.5))
                     * WARP_OFFSET_M;
    vec3 base_wp = wp + drift;
    base_wp.xz += base_warp;
    float b1 = texture(u_base_noise, base_wp / BASE_TILE).r;
    float b2 = texture(u_base_noise, base_wp / (BASE_TILE * BASE_RATIO)).r;
    float base = mix(b1, b2, BASE_BLEND);
    base = mix(base, 0.5, far_flat);
    base = remap(base, 0.30, 0.90, 0.0, 1.0);  // texture band -> full range
    float d = remap(base * prof, 1.0 - coverage * 0.78, 1.0, 0.0, 1.0);
    d = mix(d, coverage * prof, far_flat);
    if (d <= 0.0) return 0.0;
    float det = texture(u_detail_noise, (wp + drift * 1.6) / DETAIL_TILE).r;
    float eroded = remap(d, det * 0.5, 1.0, 0.0, 1.0);
    float detail_amt = 1.0 - smoothstep(DETAIL_FADE0_M, DETAIL_FADE1_M,
                                        view_t);
    d = mix(d, eroded, detail_amt);             // erode near edges only
    return clamp(d * coverage, 0.0, 1.0);
}

float sun_transmittance(vec3 wp, vec3 sun_dir, float view_t){
    float tau_m = 0.0;
    for (int i = 1; i <= SUN_STEPS; i++){
        tau_m += density_at(wp + sun_dir * (SUN_STEP_M * float(i)), view_t)
                 * SUN_STEP_M;
    }
    tau_m += density_at(wp + sun_dir * SUN_COARSE_DIST_M, view_t)
             * SUN_COARSE_WEIGHT_M;
    return exp(-tau_m * SIGMA * 1.6);
}

float hg(float ct, float g){
    float g2 = g * g;
    return (1.0 - g2) / pow(1.0 + g2 - 2.0 * g * ct, 1.5) * 0.0796;
}

float hash12(vec2 p){
    vec3 p3 = fract(vec3(p.xyx) * 0.1031);
    p3 += dot(p3, p3.yzx + 33.33);
    return fract((p3.x + p3.y) * p3.z);
}

void main(){
    // Ray from the camera through this pixel (camera-relative space:
    // the camera sits at the origin; u_cam_pos only offsets NOISE lookups).
    vec4 rp = u_inv_proj_rot * vec4(v_ndc, 1.0, 1.0);
    vec3 rd = normalize(rp.xyz / rp.w);

    // Slab entry/exit along the ray (horizontal slab in world Y).
    float cy = u_cam_pos.y;
    float t0, t1;
    if (abs(rd.y) < 1e-4){
        if (cy < u_cloud_base || cy > u_cloud_top) discard;
        t0 = 0.0;
        t1 = MARCH_DIST_CAP;
    } else {
        float ta = (u_cloud_base - cy) / rd.y;
        float tb = (u_cloud_top - cy) / rd.y;
        t0 = max(min(ta, tb), 0.0);
        t1 = max(ta, tb);
        if (t1 <= 0.0) discard;
        t1 = min(t1, t0 + MARCH_DIST_CAP);
    }
    if (t1 <= t0) discard;

    float ct = dot(rd, u_sun_dir);
    float phase = mix(hg(ct, 0.55), hg(ct, -0.25), 0.3);  // dual lobe
    // Ambient gradient: TOPS bright (they see the whole sky), bases
    // gray-blue.  v5 gate: this was inverted and clouds read as dark
    // charcoal masses from above.
    vec3 amb_lo = vec3(0.46, 0.51, 0.60) * 0.60;   // cloud-base ambient
    vec3 amb_hi = vec3(0.84, 0.89, 0.97) * 0.60;   // cloud-top ambient

    // Single jittered march.  Sun transmittance is cached every other lit
    // sample, and long low-density mist runs skip ahead without violating
    // the vertical dy clamp.
    float noise0 = hash12(gl_FragCoord.xy);
    float skip_mul = 1.0;
    float dt = march_dt(max(t0, DT_MIN_M), rd, skip_mul);
    float t = t0 + min(dt, 90.0) * noise0;
    float T = 1.0;
    vec3 acc = vec3(0.0);
    float cached_sun_T = 1.0;
    int lit_step = 0;
    int mist_run = 0;
    float t_hit = -1.0;                            // first real cloud hit
    for (int i = 0; i < MARCH_STEPS; i++){
            if (t > t1) break;
            vec3 wp = u_cam_pos + rd * t;
            float d = density_at(wp, t);
            if (d > 0.02){
                mist_run = 0;
                skip_mul = max(1.0, skip_mul * 0.5);
            } else {
                mist_run += 1;
                if (mist_run >= 8) skip_mul *= 2.0;
            }
            if (d > 0.003){
                if (t_hit < 0.0) t_hit = t;
                if ((lit_step % 2) == 0){
                    cached_sun_T = sun_transmittance(wp, u_sun_dir, t);
                }
                lit_step += 1;
                float sun_T = cached_sun_T;
                float ext = d * SIGMA * dt;
                // Powder: local-density form (the step-size form blew
                // out — huge grazing steps saturated it to 1 everywhere).
                float powder = 1.0 - exp(-4.0 * d);
                float hfrac = clamp((wp.y - u_cloud_base)
                                    / (u_cloud_top - u_cloud_base),
                                    0.0, 1.0);
                vec3 amb = mix(amb_lo, amb_hi, hfrac);
                amb = mix(amb * vec3(0.62, 0.70, 0.85), amb, sun_T);
                amb *= 0.50 + 0.50 * sun_T;
                // phase*10 alone is near-black at anti-solar view angles;
                // the +0.5 isotropic multiple-scattering floor keeps
                // sunlit cloud WHITE from every direction.  Powder gates
                // only the phase term - on the iso term it grayed every
                // thin top/edge (v5 gate iterations 1-2).
                vec3 s = u_sun_color * sun_T
                         * (phase * 10.0 * powder + 0.50) + amb;
                acc += T * s * (1.0 - exp(-ext));
                T *= exp(-ext);
                if (T < 0.03) break;
            }
            t += dt;
            dt = march_dt(t, rd, skip_mul);
        }
    float alpha = 1.0 - T;
    if (alpha < 0.003) discard;
    // Depth at the FIRST CLOUD HIT (locked log-depth formula).  The slab
    // ENTRY point was wrong: a camera INSIDE the slab has its entry AT
    // the camera, so clouds wrote near-zero depth and stomped over every
    // model in view (playtest 2026-07-07, orbit cam at 13 km).  First-hit
    // depth lets nearby hulls/missiles win the depth test honestly while
    // terrain still occludes distant cloud.
    vec3 hit_rel = rd * max(t_hit, 1.0);
    vec4 clip = u_proj * u_view_rot * vec4(hit_rel, 1.0);
    gl_FragDepth = log2(max(1.0 + clip.w, 1e-6)) * (u_log_depth_fcoef * 0.5);
    // Haze on the lit cloud (view vector = first hit, camera-relative).
    vec3 hazed = apply_haze(acc / max(alpha, 1e-4), hit_rel, u_cam_pos.y);
    frag = vec4(hazed * alpha, alpha);             // premultiplied
}
"""


class Clouds:
    """GL wrapper: bakes/loads the noise (one npz per seed), uploads the
    three REPEAT textures, draws the fullscreen raymarch pass after opaque
    geometry and before particles: depth TEST on, depth WRITE off,
    premultiplied blend."""

    def __init__(self, seed: int, cache_dir=Path("cache")):
        from OpenGL.GL import (GL_CLAMP_TO_EDGE, GL_LINEAR,
                               GL_LINEAR_MIPMAP_LINEAR, GL_R8, GL_RED,
                               GL_REPEAT, GL_RGB, GL_RGB8, GL_TEXTURE_2D,
                               GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER,
                               GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_R,
                               GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T,
                               GL_UNSIGNED_BYTE, glBindTexture,
                               glGenTextures, glGenerateMipmap, glTexImage2D,
                               glTexImage3D, glTexParameteri)
        from engine.mesh import Mesh          # noqa: F401  (GL context check)
        from engine.shader import Shader
        from engine.shaderlib import HAZE_GLSL

        noise = build_noise(seed, cache_dir=cache_dir)

        def _tex3(arr):
            tid = glGenTextures(1)
            glBindTexture(GL_TEXTURE_3D, tid)
            for wrap in (GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T,
                         GL_TEXTURE_WRAP_R):
                glTexParameteri(GL_TEXTURE_3D, wrap, GL_REPEAT)
            glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MIN_FILTER,
                            GL_LINEAR_MIPMAP_LINEAR)
            glTexParameteri(GL_TEXTURE_3D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            b = (np.clip(arr, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
            n = arr.shape[0]
            glTexImage3D(GL_TEXTURE_3D, 0, GL_R8, n, n, n, 0, GL_RED,
                         GL_UNSIGNED_BYTE, np.ascontiguousarray(b))
            glGenerateMipmap(GL_TEXTURE_3D)
            return tid

        self._t_base = _tex3(noise["base"])
        self._t_detail = _tex3(noise["detail"])

        tid = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tid)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER,
                        GL_LINEAR_MIPMAP_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        wb = (np.clip(noise["weather"], 0.0, 1.0) * 255.0 + 0.5).astype(
            np.uint8)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGB8, WEATHER_N, WEATHER_N, 0,
                     GL_RGB, GL_UNSIGNED_BYTE, np.ascontiguousarray(wb))
        glGenerateMipmap(GL_TEXTURE_2D)
        self._t_weather = tid

        # Fullscreen triangle (3 verts cover the screen; no index buffer).
        from OpenGL.GL import (GL_ARRAY_BUFFER, GL_FLOAT, GL_STATIC_DRAW,
                               glBindBuffer, glBindVertexArray, glBufferData,
                               glEnableVertexAttribArray, glGenBuffers,
                               glGenVertexArrays, glVertexAttribPointer)
        self._vao = glGenVertexArrays(1)
        glBindVertexArray(self._vao)
        vbo = glGenBuffers(1)
        glBindBuffer(GL_ARRAY_BUFFER, vbo)
        tri = np.array([-1.0, -1.0, 3.0, -1.0, -1.0, 3.0], dtype=np.float32)
        glBufferData(GL_ARRAY_BUFFER, tri.nbytes, tri, GL_STATIC_DRAW)
        glEnableVertexAttribArray(0)
        glVertexAttribPointer(0, 2, GL_FLOAT, False, 8, None)
        glBindVertexArray(0)
        self._vbo = vbo

        self.shader = Shader(CLOUD_VERT,
                             CLOUD_FRAG.replace("__HAZE__", HAZE_GLSL))
        self.enabled = True

    def draw(self, renderer, camera, sim_time: float) -> None:
        if not self.enabled:
            return
        from OpenGL.GL import (GL_BLEND, GL_CULL_FACE, GL_DEPTH_TEST, GL_ONE,
                               GL_ONE_MINUS_SRC_ALPHA, GL_TEXTURE0,
                               GL_TEXTURE_2D, GL_TEXTURE_3D, GL_TRIANGLES,
                               glActiveTexture, glBindTexture,
                               glBindVertexArray, glBlendFunc, glDepthMask,
                               glDisable, glDrawArrays, glEnable)
        sh = self.shader
        renderer.set_common(sh)      # proj/view_rot/sun/haze/fcoef/cam_alt
        inv = np.linalg.inv(np.asarray(renderer.proj, dtype=np.float64)
                            @ np.asarray(renderer.view_rot,
                                         dtype=np.float64))
        sh.set_mat4("u_inv_proj_rot", inv)
        sh.set_vec3("u_cam_pos", camera.eye)
        sh.set_float("u_time", float(sim_time))
        sh.set_float("u_cloud_base", CLOUD_BASE_M)
        sh.set_float("u_cloud_top", CLOUD_TOP_M)
        sh.set_float("u_coverage_bias", 0.0)
        glActiveTexture(GL_TEXTURE0)
        glBindTexture(GL_TEXTURE_3D, self._t_base)
        sh.set_int("u_base_noise", 0)
        glActiveTexture(GL_TEXTURE0 + 1)
        glBindTexture(GL_TEXTURE_3D, self._t_detail)
        sh.set_int("u_detail_noise", 1)
        glActiveTexture(GL_TEXTURE0 + 2)
        glBindTexture(GL_TEXTURE_2D, self._t_weather)
        sh.set_int("u_weather", 2)
        glActiveTexture(GL_TEXTURE0)

        glEnable(GL_DEPTH_TEST)
        glDepthMask(False)
        glEnable(GL_BLEND)
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)   # premultiplied
        # The engine declares front = CW (left-handed world, renderer.py);
        # a CCW NDC fullscreen triangle is a BACK face — cull off, like the
        # sky dome (the first screenshot gate caught the invisible pass).
        glDisable(GL_CULL_FACE)
        glBindVertexArray(self._vao)
        glDrawArrays(GL_TRIANGLES, 0, 3)
        glBindVertexArray(0)
        glEnable(GL_CULL_FACE)
        glDisable(GL_BLEND)
        glDepthMask(True)

    def bind_shadow_uniforms(self, shader, unit: int, camera,
                             sim_time: float, amount: float = 0.5) -> None:
        """Bind the mipmapped weather texture for terrain/ocean cloud shadows."""
        shader.use()
        amt = float(amount) if self.enabled else 0.0
        shader.set_float("u_cloud_amt", amt)
        if amt <= 0.0:
            return
        from OpenGL.GL import (GL_TEXTURE0, GL_TEXTURE_2D, glActiveTexture,
                               glBindTexture)
        glActiveTexture(GL_TEXTURE0 + int(unit))
        glBindTexture(GL_TEXTURE_2D, self._t_weather)
        shader.set_int("u_cloud_weather", int(unit))
        shader.set_vec2("u_cloud_cam_xz", (camera.eye[0], camera.eye[2]))
        shader.set_float("u_cloud_time", float(sim_time))
        glActiveTexture(GL_TEXTURE0)

    def delete(self) -> None:
        from OpenGL.GL import glDeleteBuffers, glDeleteTextures, \
            glDeleteVertexArrays
        glDeleteTextures([self._t_base, self._t_detail, self._t_weather])
        glDeleteVertexArrays(1, [self._vao])
        glDeleteBuffers(1, [self._vbo])
