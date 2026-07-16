"""Quality-scaled cloud renderer layered safely beside ``world.clouds``.

``CloudsV2`` subclasses the shipped renderer so it reuses the exact seeded
noise textures, weather-map shadows, density field, lighting, and fullscreen
triangle.  Its visible pass is split into:

1. the existing raymarch shader rendered into a quality-scaled MRT
   (premultiplied RGBA16F colour + R32F first-hit ray distance), then
2. a depth-aware 2x2 upscale/composite into the caller's framebuffer.

The old direct-to-framebuffer path remains available through ``super().draw``
and is selected automatically if V2 shader compilation or FBO allocation
fails.  OpenGL imports remain deferred until construction, preserving the
headless import convention used by ``world.clouds``.

Each view owns two history targets. First-hit world positions are reprojected
with the previous camera and wind offset, rejected on depth disagreement, and
neighborhood-clamped before blending. Main-view and PiP history never mix.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from world.clouds import (CLOUD_BASE_M, CLOUD_FRAG, CLOUD_TOP_M, CLOUD_VERT,
                          WEATHER_TILE_M, Clouds)
from sim.atmosphere import (CONVECTIVE_DOMAIN_M, CloudMorphology,
                            WeatherPreset, weather_preset as resolve_weather_preset,
                            weather_recipe_key)
from world.cloud_field import (DENSITY_TILE_M, LOWER_SHAPE, OCCUPANCY_BLOCK,
                               STORM_OCCUPANCY_BLOCK, STORM_SHAPE,
                               UPPER_SHAPE, build_cloud_field)


_QUALITY_SCALE = {"low": 0.20, "med": 0.26,
                  "high": 0.32, "ultra": 0.40}
# Severe systems can cover nearly the whole screen and cross 18-22 km of
# atmosphere. Temporal reprojection reconstructs them well from this slightly
# smaller working buffer, keeping the deliberately huge clouds playable.
_SEVERE_QUALITY_SCALE = {"low": 0.18, "med": 0.22,
                         "high": 0.26, "ultra": 0.30}

_MACRO_BIAS = {
    0: -1.0,  # clear
    1: 0.22,  # fair: broad clear gaps between cloud groups
    2: 0.30,
    3: 0.52,
    4: 0.05,
    5: 0.18,
    6: 0.42,
}

# Optical/render character is intentionally separate from field morphology.
# The bake owns shape and coverage; these values control how that stable field
# scatters light at runtime.  Tuple: optical, sheet, tower, storm, shadow.
_PRESET_RENDER = {
    0: (1.00, 0.00, 0.00, 0.00, 0.00),
    1: (1.00, 0.00, 0.12, 0.00, 0.45),
    2: (1.06, 0.00, 0.42, 0.08, 0.58),
    3: (1.10, 0.88, 0.04, 0.28, 0.76),
    4: (0.82, 0.18, 0.00, 0.00, 0.16),
    5: (1.16, 0.00, 0.92, 0.22, 0.68),
    6: (1.34, 0.34, 1.00, 1.00, 0.92),
}


def _macro_bias_for(preset: WeatherPreset) -> float:
    if (preset.preset_id in _MACRO_BIAS
            and preset == resolve_weather_preset(preset.preset_id)):
        return _MACRO_BIAS[preset.preset_id]
    coverage = max(
        (layer.coverage for layer in (preset.lower, preset.upper)
         if layer.enabled), default=0.0)
    return float(np.clip(0.08 + coverage * 0.48, -1.0, 0.56))


def _render_profile_for(preset: WeatherPreset) -> tuple[float, ...]:
    if (preset.preset_id in _PRESET_RENDER
            and preset == resolve_weather_preset(preset.preset_id)):
        return _PRESET_RENDER[preset.preset_id]
    layers = tuple(layer for layer in (preset.lower, preset.upper)
                   if layer.enabled)
    coverage = max((layer.coverage for layer in layers), default=0.0)
    sheet = max((1.0 if layer.morphology == CloudMorphology.STRATUS else 0.0
                 for layer in layers), default=0.0)
    tower = max((0.72 if layer.morphology == CloudMorphology.TOWERING else
                 0.25 if layer.morphology == CloudMorphology.CUMULUS else 0.0
                 for layer in layers), default=0.0)
    optical = 1.0 + 0.10 * coverage + 0.24 * preset.storm
    shadow = np.clip(0.18 + coverage * 0.62 + preset.storm * 0.18,
                     0.0, 0.95)
    return float(optical), float(sheet), float(tower), float(preset.storm), \
        float(shadow)

_COMPOSITE_FRAG = """
#version 330 core
in vec2 v_ndc;
uniform sampler2D u_cloud_color;
uniform sampler2D u_cloud_depth;
uniform mat4 u_inv_proj_rot;
uniform mat4 u_proj, u_view_rot;
uniform float u_log_depth_fcoef;
out vec4 frag;

void main(){
    vec2 uv = v_ndc * 0.5 + 0.5;
    // Hardware bilinear filtering performs the common interior upscale in
    // one color lookup.  The old path issued eight fetches plus four exp()
    // calls for every full-resolution pixel, making the composite cost more
    // than the reduced-resolution cloud march on mid-range GPUs.
    vec4 cloud = texture(u_cloud_color, uv);
    if (cloud.a < 0.003) discard;

    // Depth is NEAREST-filtered. It is valid for almost every interior cloud
    // pixel; only a thin silhouette fringe needs the four-neighbor fallback.
    float ref = texture(u_cloud_depth, uv).r;
    if (ref <= 0.0){
        ivec2 sz = textureSize(u_cloud_depth, 0);
        ivec2 hi = sz - ivec2(1);
        ivec2 p = ivec2(floor(uv * vec2(sz) - vec2(0.5)));
        float nearest = 1e30;
        for (int y = 0; y <= 1; ++y){
            for (int x = 0; x <= 1; ++x){
                float d = texelFetch(u_cloud_depth,
                    clamp(p + ivec2(x, y), ivec2(0), hi), 0).r;
                if (d > 0.0) nearest = min(nearest, d);
            }
        }
        if (nearest > 9e29) discard;
        ref = nearest;
    }

    // The R32F value is ray distance, so reconstruct the hit on this
    // full-resolution pixel's ray before applying the engine's exact log
    // depth formula.  Depth writes stay disabled; this only tests clouds
    // against the already-rendered opaque scene.
    vec4 rp = u_inv_proj_rot * vec4(v_ndc, 1.0, 1.0);
    vec3 rd = normalize(rp.xyz / rp.w);
    vec4 clip = u_proj * u_view_rot * vec4(rd * ref, 1.0);
    gl_FragDepth = log2(max(1.0 + clip.w, 1e-6))
                   * (u_log_depth_fcoef * 0.5);
    frag = cloud;
}
"""

_TEMPORAL_FRAG = """
#version 330 core
in vec2 v_ndc;
uniform sampler2D u_current_color;
uniform sampler2D u_current_depth;
uniform sampler2D u_history_color;
uniform sampler2D u_history_depth;
uniform mat4 u_current_inv_proj_rot;
uniform mat4 u_prev_proj_view_rot;
uniform vec3 u_cam_pos;
uniform vec3 u_prev_eye;
uniform vec2 u_wind_xz;
uniform float u_dt;
uniform int u_history_valid;
layout(location=0) out vec4 resolved_color;
layout(location=1) out float resolved_depth;

void main(){
    vec2 uv = v_ndc * 0.5 + 0.5;
    ivec2 sz = textureSize(u_current_color, 0);
    ivec2 px = clamp(ivec2(gl_FragCoord.xy), ivec2(0), sz - ivec2(1));
    vec4 current = texelFetch(u_current_color, px, 0);
    float current_depth = texelFetch(u_current_depth, px, 0).r;
    resolved_color = current;
    resolved_depth = current_depth;
    if (current.a <= 0.002 || current_depth <= 0.0 || u_history_valid == 0)
        return;

    vec4 rayp = u_current_inv_proj_rot * vec4(v_ndc, 1.0, 1.0);
    vec3 rd = normalize(rayp.xyz / rayp.w);
    vec3 hit_world = u_cam_pos + rd * current_depth;
    // density samples (world + wind*time), so the material point was ahead
    // by wind*dt in world space on the previous frame.
    vec3 previous_world = hit_world
        + vec3(u_wind_xz.x * u_dt, 0.0, u_wind_xz.y * u_dt);
    vec3 previous_rel = previous_world - u_prev_eye;
    vec4 clip = u_prev_proj_view_rot * vec4(previous_rel, 1.0);
    if (clip.w <= 0.0) return;
    vec2 history_uv = clip.xy / clip.w * 0.5 + 0.5;
    if (any(lessThan(history_uv, vec2(0.001)))
        || any(greaterThan(history_uv, vec2(0.999)))) return;

    float history_depth = texture(u_history_depth, history_uv).r;
    float expected_depth = length(previous_rel);
    float depth_tolerance = max(220.0, expected_depth * 0.025);
    if (history_depth <= 0.0
        || abs(history_depth - expected_depth) > depth_tolerance) return;

    vec4 history = texture(u_history_color, history_uv);
    vec4 lo = current;
    vec4 hi = current;
    for (int y = -1; y <= 1; ++y){
        for (int x = -1; x <= 1; ++x){
            ivec2 q = clamp(px + ivec2(x, y), ivec2(0), sz - ivec2(1));
            vec4 c = texelFetch(u_current_color, q, 0);
            lo = min(lo, c);
            hi = max(hi, c);
        }
    }
    history = clamp(history, lo, hi);       // variance/neighborhood clipping
    resolved_color = mix(current, history, 0.88);
}
"""


@dataclass
class _Mrt:
    fbo: int
    color: int
    depth: int


@dataclass
class _ViewTargets:
    """Current pass plus isolated ping-pong temporal history for one view."""

    width: int
    height: int
    current: _Mrt
    history: tuple[_Mrt, _Mrt]
    history_index: int = 0
    history_valid: bool = False
    prev_eye: np.ndarray | None = None
    prev_proj_view: np.ndarray | None = None
    prev_time: float = 0.0


def _v2_raymarch_source(quality: str = "high") -> str:
    """Add an R32F first-hit output to the shipped fragment shader.

    Keeping this as two narrow, asserted source edits means V2 renders the
    same density and lighting as legacy instead of maintaining a forked copy
    of the large raymarcher.
    """
    output = "out vec4 frag;"
    assignment = "frag = vec4(hazed * alpha, alpha);             // premultiplied"
    if CLOUD_FRAG.count(output) != 1 or CLOUD_FRAG.count(assignment) != 1:
        raise RuntimeError("legacy cloud shader layout changed; V2 patch is unsafe")
    src = CLOUD_FRAG.replace(
        output,
        "layout(location=0) out vec4 frag;\n"
        "layout(location=1) out float cloud_depth;",
        1,
    )
    quality = quality if quality in _QUALITY_SCALE else "high"
    march_steps = {"low": 192, "med": 224, "high": 256, "ultra": 320}[quality]
    sun_steps = {"low": 2, "med": 2, "high": 3, "ultra": 4}[quality]
    near_step = {"low": 48.0, "med": 36.0, "high": 28.0,
                 "ultra": 20.0}[quality]
    occupied_near = {"low": 160.0, "med": 120.0, "high": 100.0,
                     "ultra": 72.0}[quality]
    occupied_far = {"low": 680.0, "med": 520.0, "high": 420.0,
                    "ultra": 320.0}[quality]
    storm_near = {"low": 1_800.0, "med": 1_500.0, "high": 1_200.0,
                  "ultra": 800.0}[quality]
    storm_far = {"low": 5_600.0, "med": 4_800.0, "high": 4_200.0,
                 "ultra": 3_600.0}[quality]
    src = src.replace("const int   MARCH_STEPS   = 224;",
                      f"const int   MARCH_STEPS   = {march_steps};", 1)
    src = src.replace("const int   SUN_STEPS     = 4;",
                      f"const int   SUN_STEPS     = {sun_steps};", 1)
    src = src.replace("const float DT_MIN_M      = 60.0;",
                      f"const float DT_MIN_M      = {near_step:.1f};", 1)
    src = src.replace("const float SIGMA         = 0.018;",
                      "const float SIGMA         = 0.021;", 1)
    sampler_anchor = "uniform sampler2D u_weather;"
    field_uniforms = """
uniform sampler3D u_lower_field;
uniform sampler3D u_upper_field;
uniform sampler3D u_lower_occupancy;
uniform sampler3D u_upper_occupancy;
uniform sampler3D u_storm_field;
uniform sampler3D u_storm_occupancy;
uniform sampler2D u_high_clouds;
uniform sampler2D u_high_occupancy;
uniform float u_lower_base, u_lower_top;
uniform float u_upper_base, u_upper_top;
uniform float u_storm_base, u_storm_top;
uniform float u_high_altitude;
uniform float u_field_tile;
uniform float u_storm_domain;
uniform float u_high_tile;
uniform float u_macro_bias;
uniform float u_optical_scale;
uniform float u_sheetiness;
uniform float u_toweriness;
uniform float u_storminess;
uniform vec2 u_field_wind;
"""
    if src.count(sampler_anchor) != 1:
        raise RuntimeError("legacy cloud sampler layout changed; V2 patch is unsafe")
    src = src.replace(sampler_anchor, sampler_anchor + field_uniforms, 1)

    density_start = "float density_at(vec3 wp, float dt_step){"
    density_end = "\nfloat sun_transmittance"
    i0 = src.find(density_start)
    i1 = src.find(density_end, i0)
    if i0 < 0 or i1 < 0:
        raise RuntimeError("legacy cloud density layout changed; V2 patch is unsafe")
    stable_density = r"""float layer_sample(sampler3D field_tex, vec3 wp,
                         float layer_base, float layer_top){
    float h = (wp.y - layer_base) / max(layer_top - layer_base, 1.0);
    if (h < 0.0 || h > 1.0) return 0.0;
    vec2 drift = u_field_wind * u_time;
    vec2 uv = (wp.xz + drift) / u_field_tile;
    return textureLod(field_tex, vec3(uv.x, uv.y, h), 0.0).r;
}

float occupancy_sample(sampler3D occupancy_tex, vec3 wp,
                       float layer_base, float layer_top){
    float h = (wp.y - layer_base) / max(layer_top - layer_base, 1.0);
    if (h < 0.0 || h > 1.0) return 0.0;
    vec2 drift = u_field_wind * u_time;
    vec2 uv = (wp.xz + drift) / u_field_tile;
    return textureLod(occupancy_tex, vec3(uv.x, uv.y, h), 0.0).r;
}

float storm_layer_sample(vec3 wp){
    float h = (wp.y - u_storm_base) / max(u_storm_top - u_storm_base, 1.0);
    if (h < 0.0 || h > 1.0) return 0.0;
    vec2 drift = u_field_wind * u_time;
    vec2 uv = (wp.xz + drift) / u_storm_domain;
    return textureLod(u_storm_field, vec3(uv.x, uv.y, h), 0.0).r;
}

float storm_occupancy_sample(vec3 wp){
    float h = (wp.y - u_storm_base) / max(u_storm_top - u_storm_base, 1.0);
    if (h < 0.0 || h > 1.0) return 0.0;
    vec2 drift = u_field_wind * u_time;
    vec2 uv = (wp.xz + drift) / u_storm_domain;
    return textureLod(u_storm_occupancy, vec3(uv.x, uv.y, h), 0.0).r;
}

float regional_factor(vec3 wp){
    vec2 drift = u_field_wind * u_time;
    float region = textureLod(u_weather,
                              (wp.xz + drift) / WEATHER_TILE, 0.0).r;
    return smoothstep(0.27, 0.68, clamp(region + u_macro_bias, 0.0, 1.0));
}

vec2 high_uv_at(vec3 wp){
    vec2 drift = u_field_wind * u_time;
    return (wp.xz + drift) / u_high_tile;
}

float high_center_at(vec3 wp){
    vec2 drift = u_field_wind * u_time;
    vec2 modulator = textureLod(
        u_weather, (wp.xz + drift) / WEATHER_TILE + vec2(0.173, 0.619),
        0.0).gb;
    // High decks undulate hundreds of metres across the 300 km weather
    // geography instead of reading as one perfectly flat transparent plane.
    return u_high_altitude + (modulator.x - 0.5) * 620.0
           + (modulator.y - 0.5) * 260.0;
}

float high_occupied(vec3 wp){
    if (abs(wp.y - u_high_altitude) > 1250.0) return 0.0;
    // CPU-side periodic dilation already covers the bilinear support of the
    // density texture, reducing nine occupancy reads to one exact lookup.
    return textureLod(u_high_occupancy, high_uv_at(wp), 0.0).r;
}

float occupied_at(vec3 wp){
    float occupied = max(
        occupancy_sample(u_lower_occupancy, wp, u_lower_base, u_lower_top),
        occupancy_sample(u_upper_occupancy, wp, u_upper_base, u_upper_top));
    if (occupied > 0.0)
        occupied *= step(0.002, regional_factor(wp));
    return max(max(occupied, storm_occupancy_sample(wp)), high_occupied(wp));
}

float next_axis_boundary(float position, float direction, float cell_size){
    if (abs(direction) < 1e-5) return 1e30;
    float q = mod(position, cell_size);
    float metres = direction > 0.0 ? cell_size - q
                                   : (q > 0.001 ? q : cell_size);
    return metres / abs(direction);
}

float next_plane(float y, float dy, float plane_y){
    if (abs(dy) < 1e-5) return 1e30;
    float distance_t = (plane_y - y) / dy;
    return distance_t > 0.001 ? distance_t : 1e30;
}

float layer_y_boundary(vec3 wp, vec3 rd, float base_y, float top_y,
                       float cells_y){
    float safe_t = min(next_plane(wp.y, rd.y, base_y),
                       next_plane(wp.y, rd.y, top_y));
    if (wp.y >= base_y && wp.y <= top_y){
        float cell = max((top_y - base_y) / cells_y, 1.0);
        safe_t = min(safe_t,
                     next_axis_boundary(wp.y - base_y, rd.y, cell));
    }
    return safe_t;
}

float empty_skip_distance(vec3 wp, vec3 rd){
    vec2 drift = u_field_wind * u_time;
    float safe_t = 1e30;
    // Only pay each field's horizontal grid while the ray is vertically
    // inside that field. The old unconditional 3 km ambient grid forced
    // hundreds of empty checks through the otherwise sparse 18 km storm
    // slab, even when the camera was far above every ambient cloud.
    if ((wp.y >= u_lower_base && wp.y <= u_lower_top)
            || (wp.y >= u_upper_base && wp.y <= u_upper_top)){
        float ambient_cell = u_field_tile / 64.0;
        safe_t = min(safe_t,
                     next_axis_boundary(wp.x + drift.x, rd.x,
                                        ambient_cell));
        safe_t = min(safe_t,
                     next_axis_boundary(wp.z + drift.y, rd.z,
                                        ambient_cell));
    }
    if (wp.y >= u_storm_base && wp.y <= u_storm_top){
        float storm_cell = u_storm_domain
                           / float(textureSize(u_storm_occupancy, 0).x);
        safe_t = min(safe_t,
                     next_axis_boundary(wp.x + drift.x, rd.x, storm_cell));
        safe_t = min(safe_t,
                     next_axis_boundary(wp.z + drift.y, rd.z, storm_cell));
    }
    safe_t = min(safe_t, layer_y_boundary(wp, rd, u_lower_base,
                                          u_lower_top, 12.0));
    safe_t = min(safe_t, layer_y_boundary(wp, rd, u_upper_base,
                                          u_upper_top, 16.0));
    safe_t = min(safe_t, layer_y_boundary(wp, rd, u_storm_base,
                                          u_storm_top, 18.0));
    safe_t = min(safe_t, next_plane(wp.y, rd.y, u_high_altitude - 1250.0));
    safe_t = min(safe_t, next_plane(wp.y, rd.y, u_high_altitude + 1250.0));
    if (abs(wp.y - u_high_altitude) <= 1250.0){
        float high_cell = u_high_tile
                          / float(textureSize(u_high_clouds, 0).x);
        safe_t = min(safe_t,
                     next_axis_boundary(wp.x + drift.x, rd.x, high_cell));
        safe_t = min(safe_t,
                     next_axis_boundary(wp.z + drift.y, rd.z, high_cell));
    }
    return max(safe_t + 1.0, 1.0);
}

float density_at(vec3 wp, float dt_step){
    float storm_raw = storm_layer_sample(wp);
    float storm_mix = smoothstep(0.01, 0.20, storm_raw);
    // The baked supercell already carries its tower, wall-cloud, anvil and
    // overshoot silhouette.  Inside that very large volume, avoid paying for
    // both ambient density decks as well; the storm safely wins the max.
    float lower = 0.0;
    float upper = 0.0;
    if (storm_raw < 0.045){
        lower = layer_sample(u_lower_field, wp,
                             u_lower_base, u_lower_top);
        upper = layer_sample(u_upper_field, wp,
                             u_upper_base, u_upper_top);
    }
    // Overlapping decks/towers retain both structures without simply
    // doubling extinction in their overlap.
    float d = lower + upper * (1.0 - lower * 0.72);
    if (d > 0.0) d *= regional_factor(wp);
    d = max(d, storm_raw * (1.10 + 0.18 * u_storminess));

    // Runtime 3D shape/detail only erodes the conservative baked field; it
    // can never create density in an occupancy cell marked empty. The two
    // broad Perlin-Worley scales break up extruded walls and flat slabs.
    if (d > 0.0){
        vec3 drift3 = vec3(u_field_wind.x * u_time, 0.0,
                           u_field_wind.y * u_time);
        float lod_b = clamp(log2(max(dt_step, 1.0) / 46.9), 0.0, 6.0);
        float lod_d = clamp(log2(max(dt_step, 1.0) / 37.5), 0.0, 4.0);
        float base1 = textureLod(u_base_noise,
                                 (wp + drift3) / BASE_TILE, lod_b).r;
        float base2 = base1;
        if (storm_mix < 0.25)
            base2 = textureLod(u_base_noise,
                               (wp + drift3 + vec3(1733.0, 401.0, 947.0))
                               / (BASE_TILE * BASE_RATIO),
                               max(lod_b - 1.4, 0.0)).r;
        float billow = smoothstep(0.35, 0.86,
                                  mix(base1, base2, BASE_BLEND));
        float det1 = textureLod(u_detail_noise,
                                (wp + drift3) / DETAIL_TILE, lod_d).r;
        float det2 = det1;
        if (storm_mix < 0.25)
            det2 = textureLod(u_detail_noise,
                              (wp + drift3 + vec3(371.0, 919.0, 157.0))
                              / (DETAIL_TILE * 2.35),
                              max(lod_d - 1.0, 0.0)).r;
        float local_tower = max(u_toweriness, storm_mix);
        float local_sheet = u_sheetiness * (1.0 - storm_mix);
        float body_scale = mix(0.150, 0.178, local_tower);
        body_scale = mix(body_scale, 0.132, local_sheet);
        body_scale += 0.014 * u_storminess * storm_mix;
        float broad_cut = mix(0.040, 0.058, local_tower);
        broad_cut = mix(broad_cut, 0.014, local_sheet);
        broad_cut *= 1.0 - 0.08 * u_storminess * storm_mix;
        float fine_cut = mix(0.018 + 0.004 * local_tower,
                             0.010, local_sheet);
        float micro_cut = mix(0.008, 0.004, local_sheet);
        // All terms remain subtractive, preserving the occupancy guarantee.
        d = max(d * body_scale - (1.0 - billow) * broad_cut
                - (1.0 - det1) * fine_cut
                - (1.0 - det2) * micro_cut, 0.0);
        d *= u_optical_scale;
    }

    float high_density = 0.0;
    if (storm_mix < 0.05 && abs(wp.y - u_high_altitude) <= 1250.0){
        vec2 high_uv = high_uv_at(wp);
        vec2 high = textureLod(u_high_clouds, high_uv, 0.0).rg;
        float dh = abs(wp.y - high_center_at(wp));
        // Fine 3D modulation turns the 2D high map into layered filaments
        // while keeping its seeded large-scale silhouette and altitude
        // independent of the camera.
        float fiber = textureLod(
            u_detail_noise,
            (wp + vec3(u_field_wind.x * u_time, 0.0,
                       u_field_wind.y * u_time)) / 4800.0,
            clamp(log2(max(dt_step, 1.0) / 150.0), 0.0, 4.0)).r;
        float cirrus_field = smoothstep(0.22, 0.86, high.r);
        float strata_field = smoothstep(0.20, 0.82, high.g);
        float fiber_gate = mix(0.34, 1.18,
                               smoothstep(0.28, 0.78, fiber));
        float cirrus = cirrus_field * 0.030 * fiber_gate
                       * (1.0 - smoothstep(35.0, 225.0, dh));
        float strata = strata_field * 0.022 * mix(0.68, 1.06, fiber)
                       * (1.0 - smoothstep(90.0, 460.0, dh));
        high_density = cirrus + strata;
    }
    return clamp(max(d, high_density), 0.0, 1.0);
}

float local_storm_at(vec3 wp){
    return smoothstep(0.015, 0.24, storm_layer_sample(wp));
}
"""
    occ_x = LOWER_SHAPE[2] // OCCUPANCY_BLOCK
    lower_occ_y = LOWER_SHAPE[0] // OCCUPANCY_BLOCK
    upper_occ_y = UPPER_SHAPE[0] // OCCUPANCY_BLOCK
    storm_occ_y = STORM_SHAPE[0] // STORM_OCCUPANCY_BLOCK
    stable_density = stable_density.replace(
        "u_field_tile / 64.0", f"u_field_tile / {float(occ_x):.1f}")
    stable_density = stable_density.replace(
        "u_lower_top, 12.0", f"u_lower_top, {float(lower_occ_y):.1f}")
    stable_density = stable_density.replace(
        "u_upper_top, 16.0", f"u_upper_top, {float(upper_occ_y):.1f}")
    stable_density = stable_density.replace(
        "u_storm_top, 18.0", f"u_storm_top, {float(storm_occ_y):.1f}")
    src = src[:i0] + stable_density + src[i1:]
    old_sun_loop = """float tau_m = 0.0;
    for (int i = 1; i <= SUN_STEPS; i++){
        tau_m += density_at(wp + sun_dir * (SUN_STEP_M * float(i)),
                            dt_step) * SUN_STEP_M;
    }"""
    new_sun_loop = """float tau_m = 0.0;
    // Two fine taps plus the existing coarse tap retain the broad silver
    // edge and interior shading while bounding severe-weather lighting work.
    int active_sun_steps = (u_storminess >= 0.35)
                           ? min(SUN_STEPS, 2) : SUN_STEPS;
    for (int i = 1; i <= SUN_STEPS; i++){
        if (i <= active_sun_steps)
            tau_m += density_at(wp + sun_dir * (SUN_STEP_M * float(i)),
                                dt_step) * SUN_STEP_M;
    }"""
    if src.count(old_sun_loop) != 1:
        raise RuntimeError("legacy cloud sun loop changed; V2 patch is unsafe")
    src = src.replace(old_sun_loop, new_sun_loop, 1)
    march_lookup = """vec3 wp = u_cam_pos + rd * t;
            float d = density_at(wp, dt);"""
    occupancy_lookup = """vec3 wp = u_cam_pos + rd * t;
            if (occupied_at(wp) <= 0.0){
                // Advance only to the next conservative occupancy boundary.
                // A distance-grown dt may span several cells and miss clouds.
                t += empty_skip_distance(wp, rd);
                dt = march_dt(t, rd, 1.0);
                mist_run = 0;
                skip_mul = 1.0;
                continue;
            }
            // Close clouds keep fine, stable sampling. Far clouds expand only
            // to roughly one baked voxel, avoiding both horizon exhaustion
            // and the old multi-kilometre strides that skipped whole puffs.
            float occupied_cap = mix(__OCCUPIED_NEAR__, __OCCUPIED_FAR__,
                                     smoothstep(4000.0, 30000.0, t));
            // A supercell density voxel is about 4.2 km wide and its
            // silhouette is baked
            // at battle scale. March it more coarsely than small ambient
            // puffs, while keeping close/Ultra sampling comfortably sub-voxel.
            float storm_cap = mix(__STORM_NEAR__, __STORM_FAR__,
                                  smoothstep(4000.0, 50000.0, t));
            float storm_occ = smoothstep(0.001, 0.05,
                                         storm_occupancy_sample(wp));
            occupied_cap = mix(occupied_cap, storm_cap, storm_occ);
            dt = min(dt, occupied_cap);
            float d = density_at(wp, dt);"""
    occupancy_lookup = occupancy_lookup.replace(
        "__OCCUPIED_NEAR__", f"{occupied_near:.1f}").replace(
        "__OCCUPIED_FAR__", f"{occupied_far:.1f}").replace(
        "__STORM_NEAR__", f"{storm_near:.1f}").replace(
        "__STORM_FAR__", f"{storm_far:.1f}")
    if src.count(march_lookup) != 1:
        raise RuntimeError("legacy cloud march layout changed; V2 occupancy patch is unsafe")
    src = src.replace(march_lookup, occupancy_lookup, 1)
    old_light = """vec3 s = u_sun_color * sun_T
                         * (phase * 10.0 * powder + 0.50) + amb;"""
    new_light = """vec3 s = u_sun_color * sun_T
                         * (phase * 6.5 * powder + 0.42) + amb * 0.95;
                // The engine has no HDR tonemapper. Keep cloud radiance in a
                // display-safe range so thin foreground wisps cannot reveal
                // a fluorescent background cloud. A soft shoulder preserves
                // shape contrast where a hard clamp made every sunny top the
                // same featureless white.
                s = max(s, vec3(0.0));
                s = clamp((s / (s + vec3(0.55))) * 1.10,
                          vec3(0.0), vec3(0.92));
                // Deep storm interiors lose warm direct light while their
                // sun-facing anvils can still carry a bright silver edge.
                float storm_depth = u_storminess * local_storm_at(wp)
                                    * (0.22 + 0.78 * (1.0 - sun_T));
                s = mix(s, s * vec3(0.50, 0.58, 0.70),
                        clamp(storm_depth * 0.72, 0.0, 0.78));"""
    if src.count(old_light) != 1:
        raise RuntimeError("legacy cloud lighting layout changed; V2 patch is unsafe")
    src = src.replace(old_light, new_light, 1)
    old_accum = "acc += T * s * (1.0 - exp(-ext));"
    new_accum = """vec3 sample_hazed = apply_haze(s, rd * t, u_cam_pos.y);
                acc += T * sample_hazed * (1.0 - exp(-ext));"""
    if src.count(old_accum) != 1:
        raise RuntimeError("legacy cloud accumulation layout changed; V2 patch is unsafe")
    src = src.replace(old_accum, new_accum, 1)
    old_final = """vec3 hazed = apply_haze(acc / max(alpha, 1e-4), hit_rel, u_cam_pos.y);
    frag = vec4(hazed * alpha, alpha);             // premultiplied"""
    new_final = """frag = vec4(acc, alpha);       // already per-depth hazed + premultiplied
    cloud_depth = max(t_hit, 0.0);"""
    if src.count(old_final) != 1:
        raise RuntimeError("legacy cloud final-color layout changed; V2 patch is unsafe")
    src = src.replace(old_final, new_final, 1)
    # The legacy renderer's blind 5x stride is the reproduced cause of small
    # puffs disappearing during close approaches.  V2 samples continuously
    # until the conservative occupancy field replaces this temporary path.
    skip = "if (mist_run >= 8) skip_mul = min(skip_mul * 2.0, 5.0);"
    if src.count(skip) != 1:
        raise RuntimeError("legacy cloud skip layout changed; V2 patch is unsafe")
    return src.replace(skip, "skip_mul = 1.0;", 1)


class CloudsV2(Clouds):
    """Legacy-compatible, quality-scaled OpenGL 3.3 cloud renderer.

    ``draw`` accepts the legacy three arguments.  ``viewport`` and
    ``view_id`` are optional additions for offset/PiP views; omitting the
    viewport uses the currently bound GL viewport.
    """

    _MAX_CACHED_VIEWS = 4

    def __init__(self, seed: int, cache_dir=None, quality: str = "high",
                 weather_preset: int | str | WeatherPreset = 1):
        # Match Clouds' default without importing pathlib at GL construction.
        if cache_dir is None:
            from pathlib import Path
            cache_dir = Path("cache")
        super().__init__(seed, cache_dir=cache_dir)
        self.backend_name = "v2"
        self._views: OrderedDict[str, _ViewTargets] = OrderedDict()
        self._raymarch_v2 = None
        self._temporal = None
        self._composite = None
        self._v2_available = False
        self._fallback_reported = False
        self._deleted = False
        self._quality = quality if quality in _QUALITY_SCALE else "high"
        self._weather_spec = resolve_weather_preset(weather_preset)
        self._weather_preset = self._weather_spec.preset_id
        self._weather_key = weather_recipe_key(self._weather_spec)
        self._seed = int(seed)
        self._cache_dir = cache_dir
        self._field = None
        self._field_textures: list[int] = []
        self._t_lower_field = 0
        self._t_upper_field = 0
        self._t_lower_occupancy = 0
        self._t_upper_occupancy = 0
        self._t_storm_field = 0
        self._t_storm_occupancy = 0
        self._t_high_clouds = 0
        self._t_high_occupancy = 0
        self._t_shadow_v2 = 0
        self._cloud_base = CLOUD_BASE_M
        self._cloud_top = CLOUD_TOP_M
        self._high_altitude = 10_500.0
        self._field_wind = (3.0, 1.05)
        self._shadow_tile = DENSITY_TILE_M
        self._macro_bias = _macro_bias_for(self._weather_spec)
        (self._optical_scale, self._sheetiness, self._toweriness,
         self._storminess, self._shadow_amount) = _render_profile_for(
             self._weather_spec)

        try:
            from engine.shader import Shader
            from engine.shaderlib import HAZE_GLSL
            sampling_quality = self._quality
            if (self._weather_spec.supercells.enabled
                    and sampling_quality == "ultra"):
                # Ultra keeps its sharper reconstruction buffer, but the
                # severe-volume march uses High's already sub-voxel spacing.
                sampling_quality = "high"
            self._raymarch_v2 = Shader(
                CLOUD_VERT, _v2_raymarch_source(sampling_quality).replace(
                    "__HAZE__", HAZE_GLSL))
            self._temporal = Shader(CLOUD_VERT, _TEMPORAL_FRAG)
            self._composite = Shader(CLOUD_VERT, _COMPOSITE_FRAG)
            self._build_and_upload_field(seed, cache_dir)
            self._v2_available = True
        except Exception as exc:  # a working legacy object is already owned
            self.backend_name = "legacy-fallback"
            self._delete_field_textures()
            self._delete_v2_programs()
            self._report_fallback(exc)

    @property
    def using_v2(self) -> bool:
        # Backend identity, independent of CLEAR intentionally disabling draw.
        return bool(self._v2_available)

    @property
    def quality(self) -> str:
        return self._quality

    def set_quality(self, quality: str) -> None:
        quality = quality if quality in _QUALITY_SCALE else "high"
        if quality != self._quality:
            self._quality = quality
            self.reset_history()

    def set_weather_preset(self,
                           weather_preset: int | str | WeatherPreset) -> None:
        spec = resolve_weather_preset(weather_preset)
        key = weather_recipe_key(spec)
        if key != self._weather_key:
            self._weather_spec = spec
            self._weather_preset = spec.preset_id
            self._weather_key = key
            self.reset_history()
            self._delete_field_textures()
            self.enabled = True
            try:
                self._build_and_upload_field(self._seed, self._cache_dir)
            except Exception as exc:
                self._v2_available = False
                self.backend_name = "legacy-fallback"
                self._report_fallback(exc)

    def _report_fallback(self, exc: Exception) -> None:
        if not self._fallback_reported:
            print(f"[clouds_v2] V2 unavailable; using legacy clouds: {exc}")
            self._fallback_reported = True

    # ---------------------------------------------------------- stable field

    def _upload_field_3d(self, array, linear: bool) -> int:
        gl = self._gl()
        arr = np.ascontiguousarray(array, dtype=np.uint8)
        tid = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_3D, tid)
        filt = gl.GL_LINEAR if linear else gl.GL_NEAREST
        gl.glTexParameteri(gl.GL_TEXTURE_3D, gl.GL_TEXTURE_MIN_FILTER, filt)
        gl.glTexParameteri(gl.GL_TEXTURE_3D, gl.GL_TEXTURE_MAG_FILTER, filt)
        gl.glTexParameteri(gl.GL_TEXTURE_3D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_3D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_3D, gl.GL_TEXTURE_WRAP_R,
                           gl.GL_CLAMP_TO_EDGE)
        # NumPy is [y,z,x]; GL's width/height/depth are [x,z,y].
        gl.glTexImage3D(gl.GL_TEXTURE_3D, 0, gl.GL_R8,
                        arr.shape[2], arr.shape[1], arr.shape[0], 0,
                        gl.GL_RED, gl.GL_UNSIGNED_BYTE, arr)
        return tid

    def _upload_field_2d(self, array, linear: bool) -> int:
        gl = self._gl()
        arr = np.ascontiguousarray(array, dtype=np.uint8)
        channels = 1 if arr.ndim == 2 else int(arr.shape[2])
        if channels == 1:
            internal, pixel_format = gl.GL_R8, gl.GL_RED
        elif channels == 2:
            internal, pixel_format = gl.GL_RG8, gl.GL_RG
        else:
            raise ValueError("cloud field 2D texture must have one or two channels")
        tid = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D, tid)
        filt = gl.GL_LINEAR if linear else gl.GL_NEAREST
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, filt)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, filt)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_REPEAT)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_REPEAT)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, internal,
                        arr.shape[1], arr.shape[0], 0, pixel_format,
                        gl.GL_UNSIGNED_BYTE, arr)
        return tid

    @staticmethod
    def _high_occupancy_map(high_clouds) -> np.ndarray:
        """Return a periodic one-texel dilation of both high-cloud channels."""

        source = np.max(np.asarray(high_clouds), axis=2) > 0
        occupied = np.zeros(source.shape, dtype=bool)
        for dz in (-1, 0, 1):
            for dx in (-1, 0, 1):
                occupied |= np.roll(source, (dz, dx), axis=(0, 1))
        return occupied.astype(np.uint8) * np.uint8(255)

    def _build_and_upload_field(self, seed: int, cache_dir) -> None:
        preset = self._weather_spec
        field = build_cloud_field(seed, preset,
                                  cache_dir=cache_dir)
        gl = self._gl()
        unpack = int(gl.glGetIntegerv(gl.GL_UNPACK_ALIGNMENT))
        gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, 1)
        try:
            self._t_lower_field = self._upload_field_3d(
                field.lower_density, linear=True)
            self._t_upper_field = self._upload_field_3d(
                field.upper_density, linear=True)
            self._t_lower_occupancy = self._upload_field_3d(
                field.lower_occupancy, linear=False)
            self._t_upper_occupancy = self._upload_field_3d(
                field.upper_occupancy, linear=False)
            self._t_storm_field = self._upload_field_3d(
                field.storm_density, linear=True)
            self._t_storm_occupancy = self._upload_field_3d(
                field.storm_occupancy, linear=False)
            self._t_high_clouds = self._upload_field_2d(
                field.cirrus, linear=True)
            self._t_high_occupancy = self._upload_field_2d(
                self._high_occupancy_map(field.cirrus), linear=False)
            self._t_shadow_v2 = self._upload_field_2d(
                field.shadow, linear=True)
        finally:
            gl.glPixelStorei(gl.GL_UNPACK_ALIGNMENT, unpack)
            self._field_textures = [x for x in (
                self._t_lower_field, self._t_upper_field,
                self._t_lower_occupancy, self._t_upper_occupancy,
                self._t_storm_field, self._t_storm_occupancy,
                self._t_high_clouds, self._t_high_occupancy,
                self._t_shadow_v2,
            ) if x]
        self._field = field
        self._field_wind = tuple(float(v) for v in preset.wind_ms)
        self._macro_bias = _macro_bias_for(preset)
        (self._optical_scale, self._sheetiness, self._toweriness,
         self._storminess, self._shadow_amount) = _render_profile_for(preset)
        has_volume = (preset.lower.enabled or preset.upper.enabled
                      or preset.supercells.enabled)
        if preset.supercells.enabled and field.storm_density.any():
            self._shadow_tile = CONVECTIVE_DOMAIN_M
        else:
            self._shadow_tile = DENSITY_TILE_M if has_volume else WEATHER_TILE_M
        self._high_altitude = float(preset.high.altitude_m)
        bounds = []
        for layer in (preset.lower, preset.upper):
            if layer.enabled:
                bounds.append((float(layer.base_m), float(layer.top_m)))
        if preset.supercells.enabled and field.storm_density.any():
            bounds.append((field.storm_base_m, field.storm_top_m))
        if max(preset.high.cirrus_coverage,
               preset.high.strata_coverage) > 0.02:
            bounds.append((self._high_altitude - 1250.0,
                           self._high_altitude + 1250.0))
        if bounds:
            self._cloud_base = min(lo for lo, _ in bounds)
            self._cloud_top = max(hi for _, hi in bounds)
        else:
            # CLEAR: skip both the raymarch and its aligned ground shadow.
            self.enabled = False

    def _delete_field_textures(self) -> None:
        if self._field_textures:
            self._gl().glDeleteTextures(self._field_textures)
        self._field_textures = []
        self._t_lower_field = self._t_upper_field = 0
        self._t_lower_occupancy = self._t_upper_occupancy = 0
        self._t_storm_field = self._t_storm_occupancy = 0
        self._t_high_clouds = self._t_high_occupancy = 0
        self._t_shadow_v2 = 0
        self._field = None

    # ------------------------------------------------------------ GL targets

    def _new_texture(self, internal_format, pixel_format, pixel_type,
                     width: int, height: int, linear: bool) -> int:
        gl = self._gl()
        tid = int(gl.glGenTextures(1))
        gl.glBindTexture(gl.GL_TEXTURE_2D, tid)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER,
                           gl.GL_LINEAR if linear else gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER,
                           gl.GL_LINEAR if linear else gl.GL_NEAREST)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S,
                           gl.GL_CLAMP_TO_EDGE)
        gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T,
                           gl.GL_CLAMP_TO_EDGE)
        gl.glTexImage2D(gl.GL_TEXTURE_2D, 0, internal_format, width, height, 0,
                        pixel_format, pixel_type, None)
        return tid

    @staticmethod
    def _gl():
        import OpenGL.GL as gl
        return gl

    def _allocate_mrt(self, width: int, height: int) -> _Mrt:
        gl = self._gl()
        fbo = int(gl.glGenFramebuffers(1))
        color = depth = 0
        try:
            gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, fbo)
            # Preserve temporal precision for low-alpha haze and thin cirrus.
            color = self._new_texture(gl.GL_RGBA16F, gl.GL_RGBA, gl.GL_FLOAT,
                                      width, height, linear=True)
            # Full-float ray distance keeps near-cloud reprojection stable.
            depth = self._new_texture(gl.GL_R32F, gl.GL_RED, gl.GL_FLOAT,
                                      width, height, linear=False)
            gl.glFramebufferTexture2D(gl.GL_DRAW_FRAMEBUFFER,
                                      gl.GL_COLOR_ATTACHMENT0,
                                      gl.GL_TEXTURE_2D, color, 0)
            gl.glFramebufferTexture2D(gl.GL_DRAW_FRAMEBUFFER,
                                      gl.GL_COLOR_ATTACHMENT1,
                                      gl.GL_TEXTURE_2D, depth, 0)
            gl.glDrawBuffers(2, [gl.GL_COLOR_ATTACHMENT0,
                                 gl.GL_COLOR_ATTACHMENT1])
            status = gl.glCheckFramebufferStatus(gl.GL_DRAW_FRAMEBUFFER)
            if status != gl.GL_FRAMEBUFFER_COMPLETE:
                raise RuntimeError(f"cloud MRT incomplete (0x{int(status):04x})")
            return _Mrt(fbo, color, depth)
        except Exception:
            if color or depth:
                gl.glDeleteTextures([x for x in (color, depth) if x])
            if fbo:
                gl.glDeleteFramebuffers(1, [fbo])
            raise

    def _delete_mrt(self, target: _Mrt) -> None:
        gl = self._gl()
        if target.color or target.depth:
            gl.glDeleteTextures([x for x in (target.color, target.depth) if x])
        if target.fbo:
            gl.glDeleteFramebuffers(1, [target.fbo])

    def _allocate_targets(self, width: int, height: int) -> _ViewTargets:
        allocated = []
        try:
            for _ in range(3):
                allocated.append(self._allocate_mrt(width, height))
            return _ViewTargets(width, height, allocated[0],
                                (allocated[1], allocated[2]))
        except Exception:
            for target in allocated:
                self._delete_mrt(target)
            raise

    def _delete_targets(self, target: _ViewTargets) -> None:
        self._delete_mrt(target.current)
        for history in target.history:
            self._delete_mrt(history)

    def _ensure_targets(self, view_id: str, width: int,
                        height: int) -> _ViewTargets:
        scales = (_SEVERE_QUALITY_SCALE
                  if self._weather_spec.supercells.enabled
                  else _QUALITY_SCALE)
        scale = scales[self._quality]
        half_w = max(1, int(np.ceil(int(width) * scale)))
        half_h = max(1, int(np.ceil(int(height) * scale)))
        key = str(view_id)
        old = self._views.pop(key, None)
        if old is not None and (old.width, old.height) == (half_w, half_h):
            self._views[key] = old
            return old
        if old is not None:
            self._delete_targets(old)
        target = self._allocate_targets(half_w, half_h)
        self._views[key] = target
        while len(self._views) > self._MAX_CACHED_VIEWS:
            _, stale = self._views.popitem(last=False)
            self._delete_targets(stale)
        return target

    def reset_history(self, view_id=None) -> None:
        """Drop per-view histories after cuts, resizes, or recipe changes."""
        if view_id is None:
            doomed = list(self._views.values())
            self._views.clear()
        else:
            target = self._views.pop(str(view_id), None)
            doomed = [] if target is None else [target]
        for target in doomed:
            self._delete_targets(target)

    # -------------------------------------------------------------- GL state

    def _capture_state(self):
        """Capture only the output target; restore the engine draw contract.

        Querying every texture binding/program/blend equation serialized the
        driver and cost more CPU time than the cloud composite itself.
        """
        gl = self._gl()
        return {
            "fbo": int(gl.glGetIntegerv(gl.GL_DRAW_FRAMEBUFFER_BINDING)),
            "viewport": tuple(int(x) for x in gl.glGetIntegerv(gl.GL_VIEWPORT)),
            "scissor": bool(gl.glIsEnabled(gl.GL_SCISSOR_TEST)),
        }

    def _restore_state(self, state) -> None:
        gl = self._gl()
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, state["fbo"])
        gl.glViewport(*state["viewport"])
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindVertexArray(0)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_TRUE)
        gl.glDisable(gl.GL_BLEND)
        gl.glEnable(gl.GL_CULL_FACE)
        (gl.glEnable if state["scissor"] else gl.glDisable)(gl.GL_SCISSOR_TEST)

    # --------------------------------------------------------------- passes

    def _draw_current(self, renderer, camera, cloud_time: float,
                      target: _ViewTargets) -> None:
        gl = self._gl()
        current = target.current
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, current.fbo)
        gl.glViewport(0, 0, target.width, target.height)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_CULL_FACE)
        gl.glClearBufferfv(gl.GL_COLOR, 0,
                           np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float32))
        gl.glClearBufferfv(gl.GL_COLOR, 1,
                           np.array([-1.0, 0.0, 0.0, 0.0], dtype=np.float32))

        sh = self._raymarch_v2
        renderer.set_common(sh)
        inv = np.linalg.inv(np.asarray(renderer.proj, dtype=np.float64)
                            @ np.asarray(renderer.view_rot, dtype=np.float64))
        sh.set_mat4("u_inv_proj_rot", inv)
        sh.set_vec3("u_cam_pos", camera.eye)
        sh.set_float("u_time", float(cloud_time))
        sh.set_float("u_cloud_base", self._cloud_base)
        sh.set_float("u_cloud_top", self._cloud_top)
        sh.set_float("u_lower_base", self._field.lower_base_m)
        sh.set_float("u_lower_top", self._field.lower_top_m)
        sh.set_float("u_upper_base", self._field.upper_base_m)
        sh.set_float("u_upper_top", self._field.upper_top_m)
        sh.set_float("u_storm_base", self._field.storm_base_m)
        sh.set_float("u_storm_top", self._field.storm_top_m)
        sh.set_float("u_high_altitude", self._high_altitude)
        sh.set_float("u_field_tile", DENSITY_TILE_M)
        sh.set_float("u_storm_domain", CONVECTIVE_DOMAIN_M)
        sh.set_float("u_high_tile", WEATHER_TILE_M)
        sh.set_float("u_macro_bias", self._macro_bias)
        sh.set_float("u_optical_scale", self._optical_scale)
        sh.set_float("u_sheetiness", self._sheetiness)
        sh.set_float("u_toweriness", self._toweriness)
        sh.set_float("u_storminess", self._storminess)
        sh.set_vec2("u_field_wind", self._field_wind)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_3D, self._t_base)
        sh.set_int("u_base_noise", 0)
        gl.glActiveTexture(gl.GL_TEXTURE0 + 1)
        gl.glBindTexture(gl.GL_TEXTURE_3D, self._t_detail)
        sh.set_int("u_detail_noise", 1)
        gl.glActiveTexture(gl.GL_TEXTURE0 + 2)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._t_weather)
        sh.set_int("u_weather", 2)
        for unit, texture_target, texture, uniform in (
            (3, gl.GL_TEXTURE_3D, self._t_lower_field, "u_lower_field"),
            (4, gl.GL_TEXTURE_3D, self._t_upper_field, "u_upper_field"),
            (5, gl.GL_TEXTURE_3D, self._t_lower_occupancy,
             "u_lower_occupancy"),
            (6, gl.GL_TEXTURE_3D, self._t_upper_occupancy,
             "u_upper_occupancy"),
            (7, gl.GL_TEXTURE_2D, self._t_high_clouds, "u_high_clouds"),
            (8, gl.GL_TEXTURE_2D, self._t_high_occupancy,
             "u_high_occupancy"),
            (9, gl.GL_TEXTURE_3D, self._t_storm_field, "u_storm_field"),
            (10, gl.GL_TEXTURE_3D, self._t_storm_occupancy,
             "u_storm_occupancy"),
        ):
            gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
            gl.glBindTexture(texture_target, texture)
            sh.set_int(uniform, unit)
        gl.glBindVertexArray(self._vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

    def _draw_temporal(self, renderer, camera, cloud_time: float,
                       target: _ViewTargets) -> _Mrt:
        gl = self._gl()
        dt = float(cloud_time) - float(target.prev_time)
        history_ok = bool(
            target.history_valid and target.prev_eye is not None
            and target.prev_proj_view is not None and 0.0 <= dt <= 0.25
            and np.linalg.norm(np.asarray(camera.eye) - target.prev_eye)
            <= 10_000.0)
        read_index = target.history_index if history_ok else 1
        read = target.history[read_index]
        write_index = 1 - read_index
        write = target.history[write_index]

        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, write.fbo)
        gl.glViewport(0, 0, target.width, target.height)
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glDisable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glDisable(gl.GL_BLEND)
        gl.glDisable(gl.GL_CULL_FACE)

        current_pv = (np.asarray(renderer.proj, dtype=np.float64)
                      @ np.asarray(renderer.view_rot, dtype=np.float64))
        current_inv = np.linalg.inv(current_pv)
        sh = self._temporal
        sh.use()
        sh.set_mat4("u_current_inv_proj_rot", current_inv)
        sh.set_mat4("u_prev_proj_view_rot",
                    target.prev_proj_view if history_ok else current_pv)
        sh.set_vec3("u_cam_pos", camera.eye)
        sh.set_vec3("u_prev_eye",
                    target.prev_eye if history_ok else camera.eye)
        sh.set_vec2("u_wind_xz", self._field_wind)
        sh.set_float("u_dt", max(dt, 0.0) if history_ok else 0.0)
        sh.set_int("u_history_valid", 1 if history_ok else 0)
        for unit, texture, uniform in (
            (0, target.current.color, "u_current_color"),
            (1, target.current.depth, "u_current_depth"),
            (2, read.color, "u_history_color"),
            (3, read.depth, "u_history_depth"),
        ):
            gl.glActiveTexture(gl.GL_TEXTURE0 + unit)
            gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
            sh.set_int(uniform, unit)
        gl.glBindVertexArray(self._vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

        target.history_index = write_index
        target.history_valid = True
        target.prev_eye = np.asarray(camera.eye, dtype=np.float64).copy()
        target.prev_proj_view = current_pv.copy()
        target.prev_time = float(cloud_time)
        return write

    def _draw_composite(self, renderer, target: _Mrt,
                        output_fbo: int, viewport) -> None:
        gl = self._gl()
        x, y, width, height = viewport
        gl.glBindFramebuffer(gl.GL_DRAW_FRAMEBUFFER, output_fbo)
        gl.glViewport(int(x), int(y), int(width), int(height))
        gl.glDisable(gl.GL_SCISSOR_TEST)
        gl.glEnable(gl.GL_DEPTH_TEST)
        gl.glDepthMask(gl.GL_FALSE)
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_ONE, gl.GL_ONE_MINUS_SRC_ALPHA)
        gl.glDisable(gl.GL_CULL_FACE)

        sh = self._composite
        renderer.set_common(sh)
        inv = np.linalg.inv(np.asarray(renderer.proj, dtype=np.float64)
                            @ np.asarray(renderer.view_rot, dtype=np.float64))
        sh.set_mat4("u_inv_proj_rot", inv)
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, target.color)
        sh.set_int("u_cloud_color", 0)
        gl.glActiveTexture(gl.GL_TEXTURE0 + 1)
        gl.glBindTexture(gl.GL_TEXTURE_2D, target.depth)
        sh.set_int("u_cloud_depth", 1)
        gl.glBindVertexArray(self._vao)
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 3)

    def draw(self, renderer, camera, cloud_time: float, viewport=None,
             view_id="main") -> None:
        """Draw V2 clouds, falling back to the untouched legacy pass safely."""
        if not self.enabled:
            return
        if not self._v2_available:
            super().draw(renderer, camera, cloud_time)
            return

        state = self._capture_state()
        if viewport is None:
            output_viewport = state["viewport"]
        elif len(viewport) == 2:
            output_viewport = (0, 0, int(viewport[0]), int(viewport[1]))
        else:
            output_viewport = tuple(int(x) for x in viewport)
        fallback = None
        try:
            target = self._ensure_targets(view_id, output_viewport[2],
                                          output_viewport[3])
            self._draw_current(renderer, camera, cloud_time, target)
            resolved = self._draw_temporal(renderer, camera, cloud_time,
                                           target)
            self._draw_composite(renderer, resolved, state["fbo"],
                                 output_viewport)
        except Exception as exc:
            fallback = exc
            self._v2_available = False
            self.backend_name = "legacy-fallback"
            self.reset_history()
            self._delete_field_textures()
            self._delete_v2_programs()
        finally:
            self._restore_state(state)

        if fallback is not None:
            self._report_fallback(fallback)
            super().draw(renderer, camera, cloud_time)

    def bind_shadow_uniforms(self, shader, unit: int, camera,
                             cloud_time: float, amount: float = 0.5) -> None:
        """Bind the V2 field-aligned shadow map, or legacy on fallback."""
        if not self._v2_available or not self._t_shadow_v2:
            super().bind_shadow_uniforms(shader, unit, camera, cloud_time,
                                         amount=amount)
            return
        shader.use()
        amt = (min(1.0, float(amount) * self._shadow_amount / 0.5)
               if self.enabled else 0.0)
        shader.set_float("u_cloud_amt", amt)
        if amt <= 0.0:
            return
        gl = self._gl()
        gl.glActiveTexture(gl.GL_TEXTURE0 + int(unit))
        gl.glBindTexture(gl.GL_TEXTURE_2D, self._t_shadow_v2)
        shader.set_int("u_cloud_weather", int(unit))
        shader.set_vec2("u_cloud_cam_xz", (camera.eye[0], camera.eye[2]))
        shader.set_float("u_cloud_time", float(cloud_time))
        shader.set_vec2("u_cloud_wind_xz", self._field_wind)
        shader.set_float("u_cloud_tile_m", self._shadow_tile)
        gl.glActiveTexture(gl.GL_TEXTURE0)

    # ------------------------------------------------------------- teardown

    def _delete_v2_programs(self) -> None:
        gl = self._gl()
        for shader in (self._raymarch_v2, self._temporal, self._composite):
            if shader is not None and getattr(shader, "program", 0):
                gl.glDeleteProgram(shader.program)
                shader.program = 0
        self._raymarch_v2 = None
        self._temporal = None
        self._composite = None

    def delete(self) -> None:
        """Release V2 and inherited legacy resources exactly once."""
        if self._deleted:
            return
        self._deleted = True
        self.reset_history()
        self._delete_field_textures()
        self._delete_v2_programs()
        # Legacy Clouds currently does not delete its shader program.
        legacy_program = getattr(getattr(self, "shader", None), "program", 0)
        if legacy_program:
            self._gl().glDeleteProgram(legacy_program)
            self.shader.program = 0
        super().delete()
