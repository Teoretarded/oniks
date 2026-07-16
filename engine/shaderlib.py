"""Shared GLSL snippets (plain string constants — GL-free).

``world/ocean.py`` must stay importable without OpenGL (unit tests run
headless), so GLSL shared between its ocean shader and the renderer's lit
shader lives here rather than in the GL-importing ``engine/renderer.py``.
"""

# Atmospheric haze: the uniforms it reads + apply_haze(). Concatenate into a
# fragment shader body after that shader's own in/out/uniform declarations.
HAZE_GLSL = """
uniform vec3 u_sun_dir;
uniform vec3 u_haze_color, u_sun_haze_color;
uniform float u_haze_density, u_cam_alt;
vec3 apply_haze(vec3 color, vec3 view_vec, float cam_alt){
    float dist = length(view_vec);
    float h = max(cam_alt + view_vec.y * 0.5, 0.0);
    float density = u_haze_density * exp(-h / 6000.0);
    float f = 1.0 - exp(-density * dist);
    vec3 dir = view_vec / max(dist, 1.0);
    float sun_amt = pow(max(dot(dir, u_sun_dir), 0.0), 8.0);
    return mix(color, mix(u_haze_color, u_sun_haze_color, sun_amt), f);
}
"""

# Cloud shadows depend on HAZE_GLSL's u_sun_dir; do not redeclare it here.
CLOUD_SHADOW_GLSL = """
uniform sampler2D u_cloud_weather;
uniform vec2 u_cloud_cam_xz;
uniform float u_cloud_amt;
uniform float u_cloud_time;
uniform vec2 u_cloud_wind_xz;
uniform float u_cloud_tile_m;
float cloud_shadow(vec3 view_vec){
    if (u_cloud_amt <= 0.0) return 1.0;
    vec2 xz = u_cloud_cam_xz + view_vec.xz;
    xz -= (u_sun_dir.xz / max(u_sun_dir.y, 0.2)) * 2500.0;
    vec2 drift = u_cloud_time * u_cloud_wind_xz;
    float coverage = texture(u_cloud_weather,
                             (xz + drift) / max(u_cloud_tile_m, 1.0)).r;
    return 1.0 - u_cloud_amt * smoothstep(0.30, 0.75, coverage);
}
"""
